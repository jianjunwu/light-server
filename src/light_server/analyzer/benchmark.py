"""Performance Analyzer: benchmark engine for load testing inference endpoints."""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal


@dataclass
class LatencyDistribution:
    """Latency percentiles in milliseconds."""

    p50: float = 0.0
    p90: float = 0.0
    p99: float = 0.0
    p99_9: float = 0.0
    mean: float = 0.0
    min: float = 0.0
    max: float = 0.0


@dataclass
class BenchmarkResult:
    """Result of a benchmark run."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    throughput: float = 0.0  # req/s
    latency_ms: LatencyDistribution = field(default_factory=LatencyDistribution)
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute percentile from a sorted list."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100.0
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_values) else f
    if f == c:
        return sorted_values[f]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


class BenchmarkEngine:
    """Async benchmark engine supporting fixed and ramp load modes."""

    async def run(
        self,
        target: Callable[[dict[str, Any]], Awaitable[Any]],
        payload: dict[str, Any],
        mode: Literal["fixed", "ramp"] = "fixed",
        concurrency: int = 8,
        duration: float = 30.0,
        max_concurrency: int = 64,
        step_duration: float = 10.0,
        warmup_requests: int = 10,
    ) -> BenchmarkResult:
        """Run benchmark and return results.

        Args:
            target: Async function that sends a single inference request.
            payload: Request payload to send repeatedly.
            mode: "fixed" for constant concurrency, "ramp" for gradually increasing load.
            concurrency: Number of concurrent requests (fixed mode) or starting concurrency (ramp mode).
            duration: Total benchmark duration in seconds (fixed mode) or seconds per ramp step.
            max_concurrency: Maximum concurrency for ramp mode.
            step_duration: Seconds per step in ramp mode.
            warmup_requests: Number of warmup requests before measurement.
        """
        # Warmup
        for _ in range(warmup_requests):
            try:
                await target(payload)
            except Exception:
                pass

        if mode == "fixed":
            return await self._run_fixed(target, payload, concurrency, duration)
        return await self._run_ramp(
            target, payload, concurrency, max_concurrency, step_duration, duration
        )

    async def _run_fixed(
        self,
        target: Callable[[dict[str, Any]], Awaitable[Any]],
        payload: dict[str, Any],
        concurrency: int,
        duration: float,
    ) -> BenchmarkResult:
        """Fixed concurrency benchmark."""
        latencies: list[float] = []
        errors: list[str] = []
        success_count = 0
        fail_count = 0
        stop_event = asyncio.Event()

        async def worker() -> None:
            nonlocal success_count, fail_count
            while not stop_event.is_set():
                start = time.perf_counter()
                try:
                    await target(payload)
                    latency = (time.perf_counter() - start) * 1000
                    latencies.append(latency)
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    if len(errors) < 10:
                        errors.append(str(e))
                    await asyncio.sleep(0)  # yield to event loop on error

        tasks = [asyncio.create_task(worker()) for _ in range(concurrency)]
        await asyncio.sleep(duration)
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)

        return self._build_result(latencies, success_count, fail_count, duration, errors)

    async def _run_ramp(
        self,
        target: Callable[[dict[str, Any]], Awaitable[Any]],
        payload: dict[str, Any],
        start_concurrency: int,
        max_concurrency: int,
        step_duration: float,
        total_duration: float,
    ) -> BenchmarkResult:
        """Ramp-up benchmark: increase concurrency step by step."""
        latencies: list[float] = []
        errors: list[str] = []
        success_count = 0
        fail_count = 0
        stop_event = asyncio.Event()
        current_concurrency = start_concurrency
        lock = asyncio.Lock()

        async def worker() -> None:
            nonlocal success_count, fail_count
            while not stop_event.is_set():
                start = time.perf_counter()
                try:
                    await target(payload)
                    latency = (time.perf_counter() - start) * 1000
                    async with lock:
                        latencies.append(latency)
                        success_count += 1
                except Exception as e:
                    async with lock:
                        fail_count += 1
                        if len(errors) < 10:
                            errors.append(str(e))
                    await asyncio.sleep(0)  # yield to event loop on error

        tasks: list[asyncio.Task] = []
        start_time = time.perf_counter()
        step = 0

        while time.perf_counter() - start_time < total_duration:
            # Adjust worker count to current_concurrency
            while len(tasks) < current_concurrency:
                tasks.append(asyncio.create_task(worker()))
            while len(tasks) > current_concurrency:
                t = tasks.pop()
                t.cancel()

            await asyncio.sleep(step_duration)
            step += 1
            current_concurrency = min(
                start_concurrency * (2 ** step), max_concurrency
            )

        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        actual_duration = time.perf_counter() - start_time

        return self._build_result(latencies, success_count, fail_count, actual_duration, errors)

    def _build_result(
        self,
        latencies: list[float],
        success: int,
        failed: int,
        duration: float,
        errors: list[str],
    ) -> BenchmarkResult:
        sorted_lat = sorted(latencies)
        total = success + failed
        throughput = success / duration if duration > 0 else 0.0

        return BenchmarkResult(
            total_requests=total,
            successful_requests=success,
            failed_requests=failed,
            throughput=round(throughput, 2),
            latency_ms=LatencyDistribution(
                p50=round(_percentile(sorted_lat, 50), 3),
                p90=round(_percentile(sorted_lat, 90), 3),
                p99=round(_percentile(sorted_lat, 99), 3),
                p99_9=round(_percentile(sorted_lat, 99.9), 3),
                mean=round(statistics.mean(latencies), 3) if latencies else 0.0,
                min=round(sorted_lat[0], 3) if sorted_lat else 0.0,
                max=round(sorted_lat[-1], 3) if sorted_lat else 0.0,
            ),
            duration_seconds=round(duration, 2),
            errors=errors,
        )


class HttpBenchmarkTarget:
    """Convenience wrapper for HTTP-based benchmark targets."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        version: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.version = version
        self.timeout = timeout
        self._client: Any | None = None

    async def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            try:
                import httpx
                self._client = httpx.AsyncClient(timeout=self.timeout)
            except ImportError:
                raise RuntimeError(
                    "HTTP benchmark requires 'httpx'. Install it with: pip install httpx"
                )
        if self.version:
            url = f"{self.base_url}/v2/models/{self.model_name}/versions/{self.version}/infer"
        else:
            url = f"{self.base_url}/v2/models/{self.model_name}/infer"
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
