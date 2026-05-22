"""Real-time metrics aggregator for the Web UI."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from light_server.observability.collector import SystemMetrics


class MetricsAggregator:
    """Aggregates SystemMetrics data into UI-friendly formats."""

    def __init__(self, system_metrics: SystemMetrics) -> None:
        self._system_metrics = system_metrics
        self._last_counts: dict[str, int] = {}
        self._last_check: float = time.time()

    def get_summary(self) -> dict[str, Any]:
        """Return global summary metrics."""
        return {
            "timestamp": time.time(),
        }

    def get_model_metrics(self, model: str, version: str) -> dict[str, Any] | None:
        """Return real-time metrics for a specific model version."""
        key = f"{model}_{version}"
        now = time.time()

        # QPS: compute from request count delta
        current_count = self._system_metrics.get_request_count(model, version)
        last_count = self._last_counts.get(key, current_count)
        elapsed = now - self._last_check
        qps = round((current_count - last_count) / elapsed, 2) if elapsed > 0 else 0.0

        # Update stored state
        self._last_counts[key] = current_count
        if now - self._last_check > 1.0:
            self._last_check = now

        # Record QPS snapshot for sparkline
        self._system_metrics.record_qps_snapshot(model, version, qps)

        # Latency percentiles from sliding window
        samples = self._system_metrics.get_latency_samples(window_seconds=60.0)
        p50 = p90 = p99 = avg = 0.0
        if samples:
            sorted_samples = sorted(samples)
            n = len(sorted_samples)
            p50 = round(sorted_samples[int(n * 0.5)], 3) if n > 0 else 0.0
            p90 = round(sorted_samples[int(n * 0.9)], 3) if n > 0 else 0.0
            p99 = round(sorted_samples[int(n * 0.99)], 3) if n > 0 else 0.0
            avg = round(sum(samples) / len(samples), 3)

        # Queue depth from Prometheus Gauge
        try:
            queue_val = self._system_metrics.queue_depth.labels(model=model, version=version)._value.get()
        except Exception:
            queue_val = 0.0

        # Active workers
        try:
            workers_val = self._system_metrics.active_workers.labels(model=model, version=version)._value.get()
        except Exception:
            workers_val = 0.0

        # QPS history for sparkline
        history = self._system_metrics.get_qps_history(model, version)
        sparkline = self._build_sparkline(history)

        return {
            "model": model,
            "version": version,
            "qps": qps,
            "p50_ms": round(p50 * 1000, 1),
            "p90_ms": round(p90 * 1000, 1),
            "p99_ms": round(p99 * 1000, 1),
            "avg_ms": round(avg * 1000, 1),
            "queue_depth": int(queue_val),
            "active_workers": int(workers_val),
            "sparkline_svg": sparkline,
        }

    def _build_sparkline(self, history: list[tuple[float, float]]) -> str:
        """Build a tiny SVG sparkline from QPS history."""
        if len(history) < 2:
            return ""
        values = [v for _ts, v in history]
        min_v = min(values) if values else 0
        max_v = max(values) if values else 1
        if max_v == min_v:
            max_v = min_v + 1

        width = 120
        height = 30
        points: list[str] = []
        for i, v in enumerate(values):
            x = (i / (len(values) - 1)) * width
            y = height - ((v - min_v) / (max_v - min_v)) * height
            points.append(f"{x:.1f},{y:.1f}")

        path_d = f"M{points[0]}" + "".join(f" L{p}" for p in points[1:])
        return (
            f'<svg viewBox="0 0 {width} {height}" class="sparkline" width="{width}" height="{height}">'
            f'<path d="{path_d}" fill="none" stroke="currentColor" stroke-width="2"/>'
            f"</svg>"
        )
