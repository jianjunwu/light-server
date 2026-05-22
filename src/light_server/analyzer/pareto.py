"""Pareto frontier computation for multi-objective optimization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from light_server.analyzer.benchmark import BenchmarkResult
from light_server.analyzer.config_space import ModelRunConfig


@dataclass
class RunResult:
    """A single benchmark run with its configuration and metrics."""

    config: ModelRunConfig
    metrics: BenchmarkResult


def find_pareto_frontier(
    results: list[RunResult],
    objectives: list[dict[str, Any]] | None,
) -> list[RunResult]:
    """Filter results to only Pareto-optimal configurations.

    A configuration is Pareto-optimal if no other configuration is better
    in all objectives and strictly better in at least one.
    """
    if not results:
        return []

    if not objectives:
        # Default: maximize throughput, minimize p99 latency
        objectives = [
            {"metric": "throughput", "direction": "maximize"},
            {"metric": "p99_latency", "direction": "minimize"},
        ]

    def _get_value(result: RunResult, metric: str) -> float:
        if metric == "throughput":
            return result.metrics.throughput
        if metric == "p99_latency":
            return result.metrics.latency_ms.p99
        if metric == "p90_latency":
            return result.metrics.latency_ms.p90
        if metric == "mean_latency":
            return result.metrics.latency_ms.mean
        return 0.0

    def _is_better(a: float, b: float, direction: str) -> bool:
        if direction == "maximize":
            return a > b
        return a < b

    def _dominates(i: int, j: int) -> bool:
        """Return True if result[i] dominates result[j]."""
        ri, rj = results[i], results[j]
        better_in_any = False
        for obj in objectives:
            metric = obj["metric"]
            direction = obj.get("direction", "maximize")
            vi = _get_value(ri, metric)
            vj = _get_value(rj, metric)
            if _is_better(vi, vj, direction):
                better_in_any = True
            elif vi != vj:
                return False
        return better_in_any

    pareto: list[RunResult] = []
    for i in range(len(results)):
        dominated = False
        for j in range(len(results)):
            if i == j:
                continue
            if _dominates(j, i):
                dominated = True
                break
        if not dominated:
            pareto.append(results[i])

    return pareto
