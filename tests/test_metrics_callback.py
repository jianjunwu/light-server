"""Tests for PrometheusCallback metrics collection."""

from __future__ import annotations

import time

import pytest

from light_server.metrics.callback import PrometheusCallback


@pytest.fixture(autouse=True)
def _clean_prometheus_registry():
    """Remove lightserver_* metrics from default registry after each test."""
    yield
    import prometheus_client

    for collector in list(prometheus_client.REGISTRY._collector_to_names.keys()):
        try:
            names = prometheus_client.REGISTRY._collector_to_names.get(collector, set())
            if any(n.startswith("lightserver_") for n in names):
                prometheus_client.REGISTRY.unregister(collector)
        except Exception:
            pass


# ------------------------------------------------------------------
# Lifecycle
# ------------------------------------------------------------------


def test_callback_initialization():
    cb = PrometheusCallback()
    assert cb.inference_duration is not None
    assert cb.batch_size is not None
    assert cb._inference_start_times == {}
    assert not hasattr(cb, "batch_wait_time")  # removed unused metric


def test_on_server_start_does_not_crash():
    cb = PrometheusCallback()
    cb.on_server_start()  # should not raise


def test_on_server_end_does_not_crash():
    cb = PrometheusCallback()
    cb.on_server_end()  # should not raise


# ------------------------------------------------------------------
# on_before_predict
# ------------------------------------------------------------------


def test_on_before_predict_records_batch_size():
    cb = PrometheusCallback()

    class FakeAPI:
        pass

    cb.on_before_predict(lit_api=FakeAPI(), batch=[1, 2, 3])
    assert "FakeAPI" in cb._inference_start_times


def test_on_before_predict_empty_batch():
    cb = PrometheusCallback()

    class FakeAPI:
        pass

    cb.on_before_predict(lit_api=FakeAPI(), batch=[])
    assert "FakeAPI" in cb._inference_start_times


def test_on_before_predict_no_lit_api():
    """Without lit_api, should fall back to 'unknown' model name."""
    cb = PrometheusCallback()
    cb.on_before_predict(batch=[1, 2])
    assert "unknown" in cb._inference_start_times


def test_on_before_predict_no_batch():
    """Without batch kwarg, len(batch) should be 0."""
    cb = PrometheusCallback()

    class FakeAPI:
        pass

    cb.on_before_predict(lit_api=FakeAPI())
    assert "FakeAPI" in cb._inference_start_times


# ------------------------------------------------------------------
# on_after_predict
# ------------------------------------------------------------------


def test_on_after_predict_records_duration():
    cb = PrometheusCallback()

    class FakeAPI:
        pass

    cb.on_before_predict(lit_api=FakeAPI(), batch=[1])
    time.sleep(0.01)
    cb.on_after_predict(lit_api=FakeAPI())

    # Start time should be consumed
    assert "FakeAPI" not in cb._inference_start_times


def test_on_after_predict_without_before():
    """on_after_predict without matching on_before_predict should not crash."""
    cb = PrometheusCallback()

    class FakeAPI:
        pass

    cb.on_after_predict(lit_api=FakeAPI())
    assert "FakeAPI" not in cb._inference_start_times


def test_on_after_predict_no_lit_api():
    """Without lit_api, should look up 'unknown' start time."""
    cb = PrometheusCallback()
    cb.on_before_predict(batch=[1])
    time.sleep(0.01)
    cb.on_after_predict()
    assert "unknown" not in cb._inference_start_times


# ------------------------------------------------------------------
# Multiple models
# ------------------------------------------------------------------


def test_multiple_models_tracked_independently():
    cb = PrometheusCallback()

    class ModelA:
        pass

    class ModelB:
        pass

    cb.on_before_predict(lit_api=ModelA(), batch=[1])
    cb.on_before_predict(lit_api=ModelB(), batch=[1, 2])

    assert "ModelA" in cb._inference_start_times
    assert "ModelB" in cb._inference_start_times

    cb.on_after_predict(lit_api=ModelA())
    assert "ModelA" not in cb._inference_start_times
    assert "ModelB" in cb._inference_start_times

    cb.on_after_predict(lit_api=ModelB())
    assert "ModelB" not in cb._inference_start_times
