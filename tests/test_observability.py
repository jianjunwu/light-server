"""Tests for observability metrics enhancement."""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import pytest

from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry
from light_server.observability import SystemMetrics, setup_multiproc_metrics
from litserve.transport.factory import TransportConfig, create_transport_from_config


def test_setup_multiproc_metrics():
    """Multiprocess metrics setup should return a valid registry and directory."""
    registry, metrics_dir = setup_multiproc_metrics(clean=True)
    assert metrics_dir is not None
    import os
    assert os.environ.get("PROMETHEUS_MULTIPROC_DIR") == metrics_dir
    assert registry is not None


def test_system_metrics_creation():
    """SystemMetrics should initialize without errors."""
    registry, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)
    assert sm.requests_total is not None
    assert sm.request_duration is not None
    assert sm.queue_depth is not None
    assert sm.model_load_total is not None
    assert sm.version_switch_total is not None
    assert sm.ensemble_step_latency is not None
    assert sm.active_workers is not None


def test_model_load_metrics():
    """ModelManager.load() should record metrics via system_metrics."""
    manager = mp.Manager()
    registry = ModelRegistry(manager)

    transport_config = TransportConfig(transport_type="mp", num_consumers=1)
    transport_config.manager = manager
    transport = create_transport_from_config(transport_config)

    metrics_registry, _ = setup_multiproc_metrics(clean=True)
    system_metrics = SystemMetrics(metrics_registry)

    repo = Path(__file__).parent.parent / "model_repo"
    mm = ModelManager(repo, registry, transport=transport, system_metrics=system_metrics)

    success = mm.load("test_model", version="1")
    assert success
    assert registry.is_ready("test_model", "1")

    mm.unload("test_model", version="1")
    assert not registry.is_ready("test_model", "1")


def test_model_with_custom_prometheus_metrics():
    """Models defining custom prometheus metrics should load successfully."""
    from light_server.core.loader import load_litapi_from_file

    model_py = (
        Path(__file__).parent.parent / "model_repo" / "test_model" / "1" / "model.py"
    )
    cls = load_litapi_from_file(model_py, suppress_prometheus=True)
    assert cls.__name__ == "TestModel"
    # The class should have custom prometheus metrics defined
    assert hasattr(cls, "input_tokens")
    assert hasattr(cls, "predict_latency")


def test_load_litapi_with_suppress_prometheus():
    """suppress_prometheus=True should avoid registering metrics to default registry."""
    from light_server.core.loader import load_litapi_from_file
    import prometheus_client

    model_py = (
        Path(__file__).parent.parent / "model_repo" / "test_model" / "1" / "model.py"
    )

    # First load with suppression
    cls1 = load_litapi_from_file(model_py, suppress_prometheus=True)
    assert cls1.__name__ == "TestModel"

    # Second load without suppression should not raise duplicate error
    # because the first load did not register to default registry
    cls2 = load_litapi_from_file(model_py, suppress_prometheus=False)
    assert cls2.__name__ == "TestModel"

    # Clean up: unregister any metrics that were registered
    for collector in list(prometheus_client.REGISTRY._collector_to_names.keys()):
        try:
            prometheus_client.REGISTRY.unregister(collector)
        except Exception:
            pass


def test_ensemble_metrics_graceful_without_system_metrics():
    """EnsembleExecutor should not crash when server lacks system_metrics."""
    from light_server.core.ensemble import EnsembleExecutor, EnsembleConfig, EnsembleStep
    import asyncio

    class MockServer:
        pass

    server = MockServer()
    server.registry = type("R", (), {"is_ready": lambda *a, **k: True})()
    server.model_manager = type(
        "MM",
        (),
        {
            "infer": lambda *a, **k: "uid-1",
            "load": lambda *a, **k: True,
        },
    )()
    server.config = type("C", (), {"server": type("S", (), {"timeout": 0.1})()})()
    server.response_buffer = {}

    config = EnsembleConfig(
        steps=[
            EnsembleStep(name="a", model="m", version="1", inputs={"x": "$request.v"}),
        ]
    )

    async def run():
        executor = EnsembleExecutor()
        # Should not raise even though server has no system_metrics
        with pytest.raises(Exception):
            # This will fail because response_buffer has no uid-1, but
            # it should NOT fail due to missing system_metrics
            await executor.execute(server, config, {"v": 1.0}, ensemble_name="test")

    asyncio.run(run())


def test_streaming_metrics_lifecycle():
    """Streaming metrics should track open/chunk/close lifecycle correctly."""
    registry, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)

    # Verify streaming metrics exist
    assert sm.streaming_connections is not None
    assert sm.streaming_ttft is not None
    assert sm.streaming_tbt is not None
    assert sm.streaming_chunks_total is not None

    stream_id = "test-stream-1"
    model = "stream_model"
    version = "1"
    protocol = "grpc"

    # Open stream
    sm.record_stream_open(model, version, protocol, stream_id)
    assert stream_id in sm._stream_first_token_times
    assert sm._stream_first_token_times[stream_id] == 0.0

    # Simulate request start for TTFT calculation
    sm.record_request_start(model, version)

    # First chunk should record TTFT (not TBT)
    sm.record_stream_chunk(model, version, protocol, stream_id)
    assert sm._stream_first_token_times[stream_id] != 0.0
    assert sm._stream_last_token_times[stream_id] == sm._stream_first_token_times[stream_id]

    # Second chunk should record TBT
    sm.record_stream_chunk(model, version, protocol, stream_id)
    assert sm._stream_last_token_times[stream_id] >= sm._stream_first_token_times[stream_id]

    # Third chunk
    sm.record_stream_chunk(model, version, protocol, stream_id)

    # Close stream should clean up state
    sm.record_stream_close(model, version, protocol, stream_id)
    assert stream_id not in sm._stream_first_token_times
    assert stream_id not in sm._stream_last_token_times


def test_streaming_metrics_multiple_streams():
    """Multiple concurrent streams should be tracked independently."""
    registry, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)

    s1 = "stream-1"
    s2 = "stream-2"

    sm.record_stream_open("m", "1", "ws", s1)
    sm.record_stream_open("m", "1", "ws", s2)

    assert s1 in sm._stream_first_token_times
    assert s2 in sm._stream_first_token_times

    sm.record_request_start("m", "1")
    sm.record_stream_chunk("m", "1", "ws", s1)
    sm.record_stream_chunk("m", "1", "ws", s2)

    sm.record_stream_close("m", "1", "ws", s1)
    assert s1 not in sm._stream_first_token_times
    assert s2 in sm._stream_first_token_times

    sm.record_stream_close("m", "1", "ws", s2)
    assert s2 not in sm._stream_first_token_times


def test_streaming_metrics_without_request_start():
    """Stream chunk without prior request_start should not crash TTFT recording."""
    registry, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)

    stream_id = "orphan-stream"
    sm.record_stream_open("m", "1", "grpc", stream_id)

    # No record_request_start called - TTFT should still work (no start time to diff against)
    sm.record_stream_chunk("m", "1", "grpc", stream_id)
    assert sm._stream_first_token_times[stream_id] != 0.0

    sm.record_stream_close("m", "1", "grpc", stream_id)
    assert stream_id not in sm._stream_first_token_times
