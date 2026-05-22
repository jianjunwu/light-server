"""Prometheus metrics collection via LitServe Callback."""

from __future__ import annotations

import time

from litserve.callbacks import Callback
from prometheus_client import Counter, Gauge, Histogram


class PrometheusCallback(Callback):
    """Collects metrics via LitServe's callback system."""

    def __init__(self) -> None:
        self.requests_total = Counter(
            "lightserver_requests_total",
            "Total requests",
            ["model", "status"],
        )
        self.request_duration = Histogram(
            "lightserver_request_duration_seconds",
            "Request duration",
            ["model"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
        self.inference_duration = Histogram(
            "lightserver_inference_duration_seconds",
            "Inference duration",
            ["model"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
        self.active_requests = Gauge(
            "lightserver_active_requests",
            "Active requests",
            ["model"],
        )
        self.models_loaded = Gauge(
            "lightserver_models_loaded",
            "Number of loaded models",
        )
        self._request_start_times: dict[str, float] = {}
        self._inference_start_times: dict[str, float] = {}

    def on_request(self, *args, **kwargs) -> None:
        model = kwargs.get("model", "unknown")
        self.active_requests.labels(model=model).inc()
        self._request_start_times[model] = time.time()

    def on_response(self, *args, **kwargs) -> None:
        model = kwargs.get("model", "unknown")
        self.active_requests.labels(model=model).dec()
        start = self._request_start_times.pop(model, None)
        if start:
            self.request_duration.labels(model=model).observe(time.time() - start)
        self.requests_total.labels(model=model, status="ok").inc()

    def on_before_predict(self, *args, **kwargs) -> None:
        model = kwargs.get("lit_api", None)
        model_name = model.__class__.__name__ if model else "unknown"
        self._inference_start_times[model_name] = time.time()

    def on_after_predict(self, *args, **kwargs) -> None:
        model = kwargs.get("lit_api", None)
        model_name = model.__class__.__name__ if model else "unknown"
        start = self._inference_start_times.pop(model_name, None)
        if start:
            self.inference_duration.labels(model=model_name).observe(time.time() - start)

    def on_server_start(self, *args, **kwargs) -> None:
        pass

    def on_server_end(self, *args, **kwargs) -> None:
        pass
