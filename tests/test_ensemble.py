"""Tests for Model Ensemble DAG orchestration."""

import time
from pathlib import Path
from typing import Any

import pytest

from light_server.core.ensemble import (
    EnsembleConfig,
    EnsembleExecutor,
    EnsembleParser,
    EnsembleParserError,
)
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry
from litserve.transport.factory import TransportConfig, create_transport_from_config
from litserve.utils import LitAPIStatus


def _create_test_env():
    """Create manager, registry, transport, and model manager for tests."""
    import multiprocessing as mp
    manager = mp.Manager()
    registry = ModelRegistry(manager)

    transport_config = TransportConfig(transport_type="mp", num_consumers=1)
    transport_config.manager = manager
    transport = create_transport_from_config(transport_config)

    repo = Path(__file__).parent.parent / "model_repo"
    mm = ModelManager(repo, registry, transport=transport)
    return manager, registry, transport, mm


def test_list_repository_detects_ensemble():
    """list_repository should mark ensemble models correctly."""
    _m, _r, _t, mm = _create_test_env()
    models = mm.list_repository()
    ensemble = [m for m in models if m["name"] == "my_ensemble"]
    assert len(ensemble) == 1
    assert ensemble[0]["type"] == "ensemble"
    assert ensemble[0]["version"] == "1"


def test_load_ensemble_no_workers():
    """Ensemble loads instantly without spawning workers."""
    _m, registry, _t, mm = _create_test_env()
    success = mm.load("my_ensemble", version="1")
    assert success
    assert registry.is_ready("my_ensemble", "1")
    entry = registry.get("my_ensemble", "1")
    assert entry["model_type"] == "ensemble"
    assert "ensemble_config" in entry
    mm.unload("my_ensemble", version="1")


def test_ensemble_parser_cycle_detection():
    """Parser should reject cyclic DAGs."""
    config = {
        "ensemble": {
            "steps": [
                {"name": "a", "model": "m", "inputs": {"x": "$b.y"}},
                {"name": "b", "model": "m", "inputs": {"x": "$a.y"}},
            ]
        }
    }
    with pytest.raises(EnsembleParserError, match="Cycle"):
        EnsembleParser.parse(config)


def test_ensemble_parser_unresolved_ref():
    """Parser should reject references to unknown steps."""
    config = {
        "ensemble": {
            "steps": [
                {"name": "a", "model": "m", "inputs": {"x": "$unknown.y"}},
            ]
        }
    }
    with pytest.raises(EnsembleParserError, match="unknown"):
        EnsembleParser.parse(config)


def test_ensemble_parser_topological_layers():
    """Independent steps should be grouped into the same layer."""
    steps = [
        EnsembleParser.parse({
            "ensemble": {
                "steps": [
                    {"name": "a", "model": "m", "inputs": {}},
                    {"name": "b", "model": "m", "inputs": {}},
                    {"name": "c", "model": "m", "inputs": {"x": "$a.o", "y": "$b.o"}},
                ]
            }
        }).steps
    ][0]
    layers = EnsembleParser.topological_layers(steps)
    assert len(layers) == 2
    layer0_names = {s.name for s in layers[0]}
    layer1_names = {s.name for s in layers[1]}
    assert layer0_names == {"a", "b"}
    assert layer1_names == {"c"}


def test_ensemble_end_to_end():
    """Full ensemble inference with mocked sub-models."""
    import asyncio
    import threading

    _m, registry, _t, mm = _create_test_env()

    assert mm.load("my_ensemble", version="1")
    entry = registry.get("my_ensemble", "1")
    ensemble_config = entry["ensemble_config"]

    call_log: list[tuple[str, str | None, dict[str, Any]]] = []

    class MockModelManager:
        def infer(self, name, payload, version=None, response_queue_id=0):
            call_log.append((name, version, dict(payload)))
            uid = f"uid-{len(call_log)}"
            result = {"output": payload["input"] ** 2} if version == "1" else {"output": payload["input"] ** 3}

            def respond():
                item = server.response_buffer.get(uid)
                if item is not None:
                    item.response = (result, LitAPIStatus.OK)
                    loop.call_soon_threadsafe(item.event.set)

            threading.Timer(0.05, respond).start()
            return uid

        def load(self, name, version="1"):
            return True

    class MockRegistry:
        def is_ready(self, name, version=None):
            return True

    class MockServerConfig:
        timeout = 10

    class MockConfig:
        server = MockServerConfig()

    class MockServer:
        pass

    server = MockServer()
    server.model_manager = MockModelManager()
    server.registry = MockRegistry()
    server.config = MockConfig()
    server.response_buffer = {}

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        executor = EnsembleExecutor()
        result = await executor.execute(server, ensemble_config, {"value": 2.0})
        return result

    try:
        result = loop.run_until_complete(run())
        # 2 -> square(2)=4 -> cube(4)=64
        assert result == {"output": 64.0}
        assert len(call_log) == 2
        assert call_log[0] == ("test_model", "1", {"input": 2.0})
        assert call_log[1] == ("test_model", "2", {"input": 4.0})
    finally:
        loop.close()

    mm.unload("my_ensemble", version="1")


def test_ensemble_parallel_steps():
    """Independent steps are submitted in parallel via asyncio.gather."""
    import asyncio

    config = {
        "ensemble": {
            "steps": [
                {"name": "a", "model": "m", "version": "1", "inputs": {"x": "$request.v"}},
                {"name": "b", "model": "m", "version": "1", "inputs": {"x": "$request.v"}},
                {"name": "c", "model": "m", "version": "1", "inputs": {"x": "$a.o", "y": "$b.o"}},
            ]
        }
    }
    ensemble_config = EnsembleParser.parse(config)

    call_order: list[str] = []

    import threading

    class MockModelManager:
        def infer(self, name, payload, version=None, response_queue_id=0):
            uid = f"uid-{len(call_order)}"
            call_order.append(payload.get("step", "unknown"))
            result = {"o": payload["x"]}

            def respond():
                item = server.response_buffer.get(uid)
                if item is not None:
                    item.response = (result, LitAPIStatus.OK)
                    loop.call_soon_threadsafe(item.event.set)

            threading.Timer(0.05, respond).start()
            return uid

        def load(self, name, version="1"):
            return True

    class MockRegistry:
        def is_ready(self, name, version=None):
            return True

    class MockConfig:
        server = type("C", (), {"timeout": 10})()

    class MockServer:
        pass

    server = MockServer()
    server.model_manager = MockModelManager()
    server.registry = MockRegistry()
    server.config = MockConfig()
    server.response_buffer = {}

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        executor = EnsembleExecutor()
        result = loop.run_until_complete(
            executor.execute(server, ensemble_config, {"v": 5.0})
        )
        assert result == {"o": 5.0}
        # a and b are parallel, c is sequential after both
        assert len(call_order) == 3
    finally:
        loop.close()
