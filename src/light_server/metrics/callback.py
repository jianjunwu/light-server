"""Prometheus metrics collection via LitServe Callback."""

from __future__ import annotations

import time

from litserve.callbacks import Callback
from prometheus_client import Histogram


class PrometheusCallback(Callback):
    """Collects inference-level metrics via LitServe's callback system.

    These metrics are created in the worker process and aggregated
    automatically via PROMETHEUS_MULTIPROC_DIR.
    """

    def __init__(self) -> None:
        self.inference_duration = Histogram(
            "lightserver_inference_duration_seconds",
            "Time inside predict()",
            ["model"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
        self.batch_size = Histogram(
            "lightserver_batch_size",
            "Actual batch size processed",
            ["model"],
            buckets=[1, 2, 4, 8, 16, 32, 64],
        )
        self._inference_start_times: dict[str, float] = {}

    def on_before_predict(self, *args, **kwargs) -> None:
        model = kwargs.get("lit_api", None)
        model_name = model.__class__.__name__ if model else "unknown"
        batch = kwargs.get("batch", [])
        self.batch_size.labels(model=model_name).observe(len(batch))
        self._inference_start_times[model_name] = time.time()

    def on_after_predict(self, *args, **kwargs) -> None:
        model = kwargs.get("lit_api", None)
        model_name = model.__class__.__name__ if model else "unknown"
        start = self._inference_start_times.pop(model_name, None)
        if start:
            self.inference_duration.labels(model=model_name).observe(
                time.time() - start
            )

    def on_server_start(self, *args, **kwargs) -> None:
        pass

    def on_server_end(self, *args, **kwargs) -> None:
        pass
