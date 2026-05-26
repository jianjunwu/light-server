"""System-level metrics collector for the main process."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class SystemMetrics:
    """System-level metrics collected in the main process.

    These metrics are registered to the same registry as worker metrics,
    so they all appear on the same /metrics endpoint.
    """

    def __init__(self, registry: CollectorRegistry) -> None:
        self._registry = registry

        self.requests_total = Counter(
            "lightserver_requests_total",
            "Total HTTP requests",
            ["model", "version", "status"],
            registry=registry,
        )
        self.request_duration = Histogram(
            "lightserver_request_duration_seconds",
            "End-to-end request latency",
            ["model", "version"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
            registry=registry,
        )
        self.queue_depth = Gauge(
            "lightserver_queue_depth",
            "Current request queue size",
            ["model", "version"],
            registry=registry,
        )
        self.model_load_total = Counter(
            "lightserver_model_load_total",
            "Model load/unload events",
            ["model", "version", "action", "status"],
            registry=registry,
        )
        self.version_switch_total = Counter(
            "lightserver_version_switches_total",
            "Active version changes",
            ["model"],
            registry=registry,
        )
        self.ensemble_step_latency = Histogram(
            "lightserver_ensemble_step_latency_seconds",
            "Per-step latency in ensemble DAG",
            ["ensemble", "step", "model"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
            registry=registry,
        )
        self.active_workers = Gauge(
            "lightserver_active_workers",
            "Number of alive inference workers",
            ["model", "version"],
            registry=registry,
        )
        # Streaming metrics
        self.streaming_connections = Gauge(
            "lightserver_streaming_connections",
            "Active bidirectional streaming connections",
            ["model", "version", "protocol"],
            registry=registry,
        )
        self.streaming_ttft = Histogram(
            "lightserver_streaming_ttft_seconds",
            "Time to first token in streaming",
            ["model", "version", "protocol"],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
            registry=registry,
        )
        self.streaming_tbt = Histogram(
            "lightserver_streaming_tbt_seconds",
            "Time between tokens in streaming",
            ["model", "version", "protocol"],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
            registry=registry,
        )
        self.streaming_chunks_total = Counter(
            "lightserver_streaming_chunks_total",
            "Total streaming output chunks",
            ["model", "version", "protocol"],
            registry=registry,
        )
        self._request_start_times: dict[str, float] = {}
        self._stream_first_token_times: dict[str, float] = {}
        self._stream_last_token_times: dict[str, float] = {}
        self._queue_depth_values: dict[str, int] = {}
        self._active_workers_values: dict[str, int] = {}

        # UI-friendly sliding window data (not Prometheus metrics)
        self._latency_window: deque[tuple[float, float]] = deque(maxlen=2000)
        self._request_counts: dict[str, int] = {}
        self._last_rate_check: float = time.time()
        self._qps_history: dict[str, deque[tuple[float, float]]] = {}

    def record_request_start(self, model: str, version: str, request_id: str) -> None:
        """Call at request entry."""
        self._request_start_times[request_id] = time.time()

    def record_request_end(self, model: str, version: str, status: str, request_id: str) -> None:
        """Call at request exit with HTTP status category."""
        self.requests_total.labels(model=model, version=version, status=status).inc()
        start = self._request_start_times.pop(request_id, None)
        if start is not None:
            latency = time.time() - start
            self.request_duration.labels(model=model, version=version).observe(latency)
            self._latency_window.append((time.time(), latency))

        key = f"{model}_{version}"
        self._request_counts[key] = self._request_counts.get(key, 0) + 1

    def inc_queue_depth(self, model: str, version: str) -> None:
        self.queue_depth.labels(model=model, version=version).inc()
        key = f"{model}_{version}"
        self._queue_depth_values[key] = self._queue_depth_values.get(key, 0) + 1

    def dec_queue_depth(self, model: str, version: str) -> None:
        self.queue_depth.labels(model=model, version=version).dec()
        key = f"{model}_{version}"
        self._queue_depth_values[key] = max(0, self._queue_depth_values.get(key, 0) - 1)

    def get_queue_depth(self, model: str, version: str) -> int:
        return self._queue_depth_values.get(f"{model}_{version}", 0)

    def record_model_load(self, model: str, version: str, success: bool) -> None:
        status = "success" if success else "fail"
        self.model_load_total.labels(
            model=model, version=version, action="load", status=status
        ).inc()

    def record_model_unload(self, model: str, version: str) -> None:
        self.model_load_total.labels(
            model=model, version=version, action="unload", status="success"
        ).inc()

    def record_version_switch(self, model: str) -> None:
        self.version_switch_total.labels(model=model).inc()

    def record_ensemble_step_latency(
        self, ensemble: str, step: str, model: str, latency: float
    ) -> None:
        self.ensemble_step_latency.labels(
            ensemble=ensemble, step=step, model=model
        ).observe(latency)

    def set_active_workers(self, model: str, version: str, count: int) -> None:
        self.active_workers.labels(model=model, version=version).set(count)
        self._active_workers_values[f"{model}_{version}"] = count

    def get_active_workers(self, model: str, version: str) -> int:
        return self._active_workers_values.get(f"{model}_{version}", 0)

    # ------------------------------------------------------------------
    # Streaming metrics
    # ------------------------------------------------------------------

    def record_stream_open(self, model: str, version: str, protocol: str, stream_id: str) -> None:
        self.streaming_connections.labels(model=model, version=version, protocol=protocol).inc()
        self._stream_first_token_times[stream_id] = 0.0
        self._stream_last_token_times[stream_id] = 0.0

    def record_stream_chunk(
        self, model: str, version: str, protocol: str, stream_id: str
    ) -> None:
        now = time.time()
        self.streaming_chunks_total.labels(model=model, version=version, protocol=protocol).inc()

        first_time = self._stream_first_token_times.get(stream_id, 0.0)
        if first_time == 0.0:
            # First chunk: record TTFT relative to request start
            start = self._request_start_times.pop(stream_id, None)
            if start is not None:
                ttft = now - start
                self.streaming_ttft.labels(model=model, version=version, protocol=protocol).observe(ttft)
            self._stream_first_token_times[stream_id] = now
        else:
            # Subsequent chunk: record TBT
            last = self._stream_last_token_times.get(stream_id, first_time)
            tbt = now - last
            self.streaming_tbt.labels(model=model, version=version, protocol=protocol).observe(tbt)

        self._stream_last_token_times[stream_id] = now

    def record_stream_close(self, model: str, version: str, protocol: str, stream_id: str) -> None:
        self.streaming_connections.labels(model=model, version=version, protocol=protocol).dec()
        self._stream_first_token_times.pop(stream_id, None)
        self._stream_last_token_times.pop(stream_id, None)

    # ------------------------------------------------------------------
    # UI query helpers (sliding window data)
    # ------------------------------------------------------------------

    def get_latency_samples(self, window_seconds: float = 60.0) -> list[float]:
        """Return latency samples within the last N seconds."""
        cutoff = time.time() - window_seconds
        return [lat for ts, lat in self._latency_window if ts >= cutoff]

    def get_request_count(self, model: str, version: str) -> int:
        """Return total request count for a model version."""
        return self._request_counts.get(f"{model}_{version}", 0)

    def record_qps_snapshot(self, model: str, version: str, qps: float) -> None:
        """Record a QPS snapshot for sparkline history."""
        key = f"{model}_{version}"
        if key not in self._qps_history:
            self._qps_history[key] = deque(maxlen=20)
        self._qps_history[key].append((time.time(), qps))

    def get_qps_history(self, model: str, version: str) -> list[tuple[float, float]]:
        """Return QPS history for sparkline (list of (timestamp, qps))."""
        key = f"{model}_{version}"
        hist = self._qps_history.get(key, deque())
        return list(hist)
