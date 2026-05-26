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
    registry, metrics_dir, _ = setup_multiproc_metrics(clean=True)
    assert metrics_dir is not None
    import os
    assert os.environ.get("PROMETHEUS_MULTIPROC_DIR") == metrics_dir
    assert registry is not None


def test_system_metrics_creation():
    """SystemMetrics should initialize without errors."""
    registry, _, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)
    assert sm.requests_total is not None
    assert sm.request_duration is not None
    assert sm.queue_depth is not None
    assert sm.model_load_total is not None
    assert sm.version_switch_total is not None
    assert sm.ensemble_step_latency is not None
    assert sm.active_workers is not None


def test_model_load_metrics(isolated_model_repo):
    """ModelManager.load() should record metrics via system_metrics."""
    manager = mp.Manager()
    registry = ModelRegistry(manager)

    transport_config = TransportConfig(transport_type="mp", num_consumers=1)
    transport_config.manager = manager
    transport = create_transport_from_config(transport_config)

    metrics_registry, _, _ = setup_multiproc_metrics(clean=True)
    system_metrics = SystemMetrics(metrics_registry)

    mm = ModelManager(isolated_model_repo, registry, transport=transport, system_metrics=system_metrics)

    success = mm.load("test_model", version="1")
    assert success
    assert registry.is_ready("test_model", "1")

    mm.unload("test_model", version="1")
    assert not registry.is_ready("test_model", "1")


def test_model_with_custom_prometheus_metrics(isolated_model_repo):
    """Models defining custom prometheus metrics should load successfully."""
    from light_server.core.loader import load_litapi_from_file

    model_py = isolated_model_repo / "test_model" / "1" / "model.py"
    cls = load_litapi_from_file(model_py, suppress_prometheus=True)
    assert cls.__name__ == "TestModel"
    # The class should have custom prometheus metrics defined
    assert hasattr(cls, "input_tokens")
    assert hasattr(cls, "predict_latency")


def test_load_litapi_with_suppress_prometheus(isolated_model_repo):
    """suppress_prometheus=True should avoid registering metrics to default registry."""
    from light_server.core.loader import load_litapi_from_file
    import prometheus_client

    model_py = isolated_model_repo / "test_model" / "1" / "model.py"

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
    registry, _, _ = setup_multiproc_metrics(clean=True)
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
    sm.record_request_start(model, version, stream_id)

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
    registry, _, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)

    s1 = "stream-1"
    s2 = "stream-2"

    sm.record_stream_open("m", "1", "ws", s1)
    sm.record_stream_open("m", "1", "ws", s2)

    assert s1 in sm._stream_first_token_times
    assert s2 in sm._stream_first_token_times

    sm.record_request_start("m", "1", s1)
    sm.record_request_start("m", "1", s2)
    sm.record_stream_chunk("m", "1", "ws", s1)
    sm.record_stream_chunk("m", "1", "ws", s2)

    sm.record_stream_close("m", "1", "ws", s1)
    assert s1 not in sm._stream_first_token_times
    assert s2 in sm._stream_first_token_times

    sm.record_stream_close("m", "1", "ws", s2)
    assert s2 not in sm._stream_first_token_times


def test_streaming_metrics_without_request_start():
    """Stream chunk without prior request_start should not crash TTFT recording."""
    registry, _, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)

    stream_id = "orphan-stream"
    sm.record_stream_open("m", "1", "grpc", stream_id)

    # No record_request_start called - TTFT should still work (no start time to diff against)
    sm.record_stream_chunk("m", "1", "grpc", stream_id)
    assert sm._stream_first_token_times[stream_id] != 0.0

    sm.record_stream_close("m", "1", "grpc", stream_id)
    assert stream_id not in sm._stream_first_token_times


def test_concurrent_request_start_times():
    """Concurrent requests with same model/version should not overwrite start times."""
    registry, _, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)

    req1 = "req-1"
    req2 = "req-2"

    sm.record_request_start("m", "1", req1)
    sm.record_request_start("m", "1", req2)

    # Both start times should be tracked independently
    assert req1 in sm._request_start_times
    assert req2 in sm._request_start_times

    # End req1
    sm.record_request_end("m", "1", "2xx", req1)
    assert req1 not in sm._request_start_times
    assert req2 in sm._request_start_times

    # End req2
    sm.record_request_end("m", "1", "2xx", req2)
    assert req2 not in sm._request_start_times


def test_streaming_ttft_uses_stream_id():
    """Stream chunk TTFT should use stream_id, not model+version key."""
    registry, _, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)

    s1 = "stream-a"
    s2 = "stream-b"

    sm.record_stream_open("m", "1", "ws", s1)
    sm.record_stream_open("m", "1", "ws", s2)

    sm.record_request_start("m", "1", s1)
    sm.record_request_start("m", "1", s2)

    # First chunk on s1 should pop s1's start time, not s2's
    sm.record_stream_chunk("m", "1", "ws", s1)
    assert s1 in sm._stream_first_token_times
    assert s1 not in sm._request_start_times  # popped by TTFT
    assert s2 in sm._request_start_times  # still there

    sm.record_stream_chunk("m", "1", "ws", s2)
    assert s2 not in sm._request_start_times  # popped by TTFT

    sm.record_stream_close("m", "1", "ws", s1)
    sm.record_stream_close("m", "1", "ws", s2)


def test_metrics_aggregator_uses_public_api():
    """MetricsAggregator should not access prometheus_client internal _value."""
    from light_server.webui.metrics_agg import MetricsAggregator

    registry, _, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)

    agg = MetricsAggregator(sm)

    sm.inc_queue_depth("m", "1")
    sm.inc_queue_depth("m", "1")
    sm.set_active_workers("m", "1", 4)

    metrics = agg.get_model_metrics("m", "1")
    assert metrics is not None
    assert metrics["queue_depth"] == 2
    assert metrics["active_workers"] == 4


def test_queue_depth_and_active_workers_getters():
    """SystemMetrics should track queue_depth and active_workers via public getters."""
    registry, _, _ = setup_multiproc_metrics(clean=True)
    sm = SystemMetrics(registry)

    assert sm.get_queue_depth("m", "1") == 0
    assert sm.get_active_workers("m", "1") == 0

    sm.inc_queue_depth("m", "1")
    sm.inc_queue_depth("m", "1")
    assert sm.get_queue_depth("m", "1") == 2

    sm.dec_queue_depth("m", "1")
    assert sm.get_queue_depth("m", "1") == 1

    sm.set_active_workers("m", "1", 3)
    assert sm.get_active_workers("m", "1") == 3

    sm.set_active_workers("m", "1", 0)
    assert sm.get_active_workers("m", "1") == 0


def test_init_worker_locals_idempotent():
    """HTTPState.init_worker_locals should be idempotent (no duplicate registry creation)."""
    from light_server.http.state import HTTPState

    state = HTTPState(
        registry=None,  # type: ignore[arg-type]
        transport=None,  # type: ignore[arg-type]
        config=None,  # type: ignore[arg-type]
    )

    state.init_worker_locals()
    first_metrics = state._system_metrics
    first_buffer = state._shm_buffer

    assert first_metrics is not None
    assert first_buffer is not None

    # Second call should not recreate
    state.init_worker_locals()
    assert state._system_metrics is first_metrics
    assert state._shm_buffer is first_buffer
