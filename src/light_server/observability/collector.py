"""System-level metrics collector for the main process."""

from __future__ import annotations

import time
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
        self._request_start_times: dict[str, float] = {}

    def record_request_start(self, model: str, version: str) -> None:
        """Call at request entry."""
        self._request_start_times[f"{model}_{version}"] = time.time()

    def record_request_end(self, model: str, version: str, status: str) -> None:
        """Call at request exit with HTTP status category."""
        self.requests_total.labels(model=model, version=version, status=status).inc()
        start = self._request_start_times.pop(f"{model}_{version}", None)
        if start is not None:
            self.request_duration.labels(model=model, version=version).observe(
                time.time() - start
            )

    def inc_queue_depth(self, model: str, version: str) -> None:
        self.queue_depth.labels(model=model, version=version).inc()

    def dec_queue_depth(self, model: str, version: str) -> None:
        self.queue_depth.labels(model=model, version=version).dec()

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
