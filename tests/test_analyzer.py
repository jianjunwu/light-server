"""Tests for Model Analyzer and Performance Analyzer."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from light_server.analyzer.benchmark import BenchmarkEngine, BenchmarkResult, LatencyDistribution
from light_server.analyzer.config_space import AnalysisConfig, ConfigurationSpace, ModelRunConfig
from light_server.analyzer.pareto import RunResult, find_pareto_frontier
from light_server.analyzer.report import AnalysisReport, ReportGenerator


def test_benchmark_engine_fixed():
    """Fixed concurrency benchmark should measure latency accurately."""
    call_count = 0

    async def target(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.01)
        return {"output": payload["input"] * 2}

    engine = BenchmarkEngine()
    result = asyncio.run(
        engine.run(
            target=target,
            payload={"input": 1.0},
            mode="fixed",
            concurrency=4,
            duration=1.0,
            warmup_requests=0,
        )
    )

    assert result.total_requests > 0
    assert result.successful_requests > 0
    assert result.failed_requests == 0
    assert result.throughput > 0
    assert result.latency_ms.mean >= 10.0  # 0.01s = 10ms
    assert result.latency_ms.p50 >= 10.0


def test_benchmark_engine_ramp():
    """Ramp mode should increase concurrency over time."""
    max_concurrent = 0
    current_concurrent = 0
    lock = asyncio.Lock()

    async def target(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal max_concurrent, current_concurrent
        async with lock:
            current_concurrent += 1
            if current_concurrent > max_concurrent:
                max_concurrent = current_concurrent
        await asyncio.sleep(0.01)
        async with lock:
            current_concurrent -= 1
        return {"output": 1}

    engine = BenchmarkEngine()
    result = asyncio.run(
        engine.run(
            target=target,
            payload={"input": 1.0},
            mode="ramp",
            concurrency=2,
            duration=2.0,
            max_concurrency=8,
            step_duration=0.5,
            warmup_requests=0,
        )
    )

    assert result.total_requests > 0
    assert max_concurrent > 2  # Should have ramped up


def test_benchmark_result_with_errors():
    """Benchmark should count errors correctly."""
    async def target(payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("simulated error")

    engine = BenchmarkEngine()
    result = asyncio.run(
        engine.run(
            target=target,
            payload={"input": 1.0},
            mode="fixed",
            concurrency=2,
            duration=0.5,
            warmup_requests=0,
        )
    )

    assert result.failed_requests > 0
    assert result.successful_requests == 0
    assert len(result.errors) > 0


def test_configuration_space():
    """ConfigurationSpace should produce Cartesian product."""
    cfg = AnalysisConfig(
        batch_sizes=[1, 2],
        workers_per_device=[1],
        concurrency_levels=[1, 4],
    )
    space = ConfigurationSpace(cfg)
    configs = space.iterate()

    assert len(configs) == 4
    assert space.total_combinations == 4

    # Check all combinations exist
    keys = [(c.batch_size, c.workers_per_device, c.concurrency) for c in configs]
    assert (1, 1, 1) in keys
    assert (1, 1, 4) in keys
    assert (2, 1, 1) in keys
    assert (2, 1, 4) in keys


def test_pareto_frontier_maximize_throughput():
    """Pareto frontier should keep non-dominated points."""
    results = [
        RunResult(ModelRunConfig(1, 1, 1), BenchmarkResult(throughput=100, latency_ms=type("L", (), {"p99": 50.0})())),
        RunResult(ModelRunConfig(2, 1, 2), BenchmarkResult(throughput=200, latency_ms=type("L", (), {"p99": 60.0})())),
        RunResult(ModelRunConfig(4, 2, 4), BenchmarkResult(throughput=150, latency_ms=type("L", (), {"p99": 80.0})())),
    ]

    pareto = find_pareto_frontier(results, objectives=[{"metric": "throughput", "direction": "maximize"}])

    # Only the highest throughput should remain
    assert len(pareto) == 1
    assert pareto[0].metrics.throughput == 200


def test_pareto_frontier_multi_objective():
    """Multi-objective Pareto should keep trade-off points."""
    results = [
        RunResult(ModelRunConfig(1, 1, 1), BenchmarkResult(throughput=100, latency_ms=type("L", (), {"p99": 20.0})())),
        RunResult(ModelRunConfig(2, 1, 2), BenchmarkResult(throughput=200, latency_ms=type("L", (), {"p99": 30.0})())),
        RunResult(ModelRunConfig(4, 2, 4), BenchmarkResult(throughput=150, latency_ms=type("L", (), {"p99": 80.0})())),
    ]

    pareto = find_pareto_frontier(
        results,
        objectives=[
            {"metric": "throughput", "direction": "maximize"},
            {"metric": "p99_latency", "direction": "minimize"},
        ],
    )

    # Config 3 (150, 80) is dominated by Config 2 (200, 30) in both objectives
    assert len(pareto) == 2
    throughputs = {r.metrics.throughput for r in pareto}
    assert throughputs == {100, 200}


def test_report_generator_console():
    """Console report should contain key data."""
    from datetime import datetime, timezone

    report = AnalysisReport(
        model="test_model",
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_combinations=4,
        all_results=[],
        pareto_frontier=[
            RunResult(
                ModelRunConfig(4, 2, 8),
                BenchmarkResult(throughput=420.0, latency_ms=type("L", (), {"p99": 12.3, "p90": 8.0, "mean": 6.0})()),
            ),
        ],
    )

    text = ReportGenerator.to_console(report)
    assert "test_model" in text
    assert "420.0" in text
    assert "12.3" in text


def test_report_generator_json():
    """JSON report should be valid and complete."""
    import json
    from datetime import datetime, timezone

    report = AnalysisReport(
        model="test_model",
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_combinations=2,
        all_results=[],
        pareto_frontier=[
            RunResult(
                ModelRunConfig(1, 1, 1),
                BenchmarkResult(throughput=100.0, latency_ms=LatencyDistribution(p99=10.0, p90=5.0, mean=3.0)),
            ),
        ],
    )

    json_str = ReportGenerator.to_json(report)
    data = json.loads(json_str)
    assert data["model"] == "test_model"
    assert data["total_combinations"] == 2
    assert len(data["pareto_frontier"]) == 1
    assert data["pareto_frontier"][0]["metrics"]["throughput"] == 100.0


def test_analysis_config_from_dict():
    """AnalysisConfig should parse from dict correctly."""
    cfg = AnalysisConfig.from_dict({
        "batch_sizes": [1, 4, 8],
        "workers_per_device": [1, 2],
        "concurrency_levels": [1, 4],
        "duration_per_config": 20.0,
        "payload": {"input": 2.0},
    })

    assert cfg.batch_sizes == [1, 4, 8]
    assert cfg.workers_per_device == [1, 2]
    assert cfg.concurrency_levels == [1, 4]
    assert cfg.duration_per_config == 20.0
    assert cfg.payload == {"input": 2.0}


def test_cli_benchmark_parser():
    """CLI should accept benchmark subcommand arguments."""
    from light_server.cli import main

    # Just verify parsing doesn't crash
    with pytest.raises(SystemExit) as exc_info:
        main(["benchmark", "--help"])
    assert exc_info.value.code == 0


def test_cli_analyze_parser():
    """CLI should accept analyze subcommand arguments."""
    from light_server.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["analyze", "--help"])
    assert exc_info.value.code == 0
