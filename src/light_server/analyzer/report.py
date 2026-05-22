"""Report generation for Model Analyzer results."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from light_server.analyzer.benchmark import BenchmarkResult
from light_server.analyzer.config_space import ModelRunConfig
from light_server.analyzer.pareto import RunResult


@dataclass
class AnalysisReport:
    """Complete analysis report for a model."""

    model: str
    timestamp: str
    total_combinations: int
    all_results: list[RunResult]
    pareto_frontier: list[RunResult]


class ReportGenerator:
    """Generate human-readable and machine-readable reports."""

    @staticmethod
    def to_json(report: AnalysisReport, indent: int = 2) -> str:
        """Serialize report to JSON."""
        data = {
            "model": report.model,
            "timestamp": report.timestamp,
            "total_combinations": report.total_combinations,
            "pareto_frontier": [
                {
                    "config": {
                        "batch_size": r.config.batch_size,
                        "workers_per_device": r.config.workers_per_device,
                        "concurrency": r.config.concurrency,
                    },
                    "metrics": {
                        "throughput": r.metrics.throughput,
                        "latency_ms": asdict(r.metrics.latency_ms),
                        "successful_requests": r.metrics.successful_requests,
                        "failed_requests": r.metrics.failed_requests,
                    },
                }
                for r in report.pareto_frontier
            ],
            "all_results": [
                {
                    "config": {
                        "batch_size": r.config.batch_size,
                        "workers_per_device": r.config.workers_per_device,
                        "concurrency": r.config.concurrency,
                    },
                    "metrics": {
                        "throughput": r.metrics.throughput,
                        "latency_ms": asdict(r.metrics.latency_ms),
                        "successful_requests": r.metrics.successful_requests,
                        "failed_requests": r.metrics.failed_requests,
                    },
                }
                for r in report.all_results
            ],
        }
        return json.dumps(data, indent=indent, default=str)

    @staticmethod
    def to_markdown(report: AnalysisReport) -> str:
        """Generate a Markdown table summary."""
        lines = [
            f"# Model Analyzer Report: {report.model}",
            "",
            f"**Total combinations tested:** {report.total_combinations}",
            f"**Pareto optimal:** {len(report.pareto_frontier)}",
            "",
            "## Pareto Optimal Configurations",
            "",
            "| Batch Size | Workers/Device | Concurrency | Throughput (req/s) | P99 Latency (ms) | P90 (ms) | Mean (ms) |",
            "|-----------:|---------------:|------------:|-------------------:|-----------------:|---------:|----------:|",
        ]
        for r in report.pareto_frontier:
            lines.append(
                f"| {r.config.batch_size} | {r.config.workers_per_device} | "
                f"{r.config.concurrency} | {r.metrics.throughput} | "
                f"{r.metrics.latency_ms.p99} | {r.metrics.latency_ms.p90} | "
                f"{r.metrics.latency_ms.mean} |"
            )
        lines.append("")
        lines.append("## Recommendations")
        lines.append("")
        if report.pareto_frontier:
            # Sort by p99 latency for latency-sensitive recommendation
            by_latency = sorted(report.pareto_frontier, key=lambda x: x.metrics.latency_ms.p99)
            best_latency = by_latency[0]
            lines.append(
                f"- **Latency-sensitive**: Batch={best_latency.config.batch_size}, "
                f"Workers={best_latency.config.workers_per_device}, "
                f"Concurrency={best_latency.config.concurrency} "
                f"(P99={best_latency.metrics.latency_ms.p99}ms, "
                f"Throughput={best_latency.metrics.throughput} req/s)"
            )
            # Sort by throughput for throughput-oriented recommendation
            by_throughput = sorted(report.pareto_frontier, key=lambda x: x.metrics.throughput, reverse=True)
            best_throughput = by_throughput[0]
            lines.append(
                f"- **Throughput-oriented**: Batch={best_throughput.config.batch_size}, "
                f"Workers={best_throughput.config.workers_per_device}, "
                f"Concurrency={best_throughput.config.concurrency} "
                f"(Throughput={best_throughput.metrics.throughput} req/s, "
                f"P99={best_throughput.metrics.latency_ms.p99}ms)"
            )
        else:
            lines.append("No Pareto optimal configurations found.")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def to_console(report: AnalysisReport) -> str:
        """Generate a compact console summary."""
        lines = [
            "=" * 70,
            f"Model Analyzer Report: {report.model}",
            "=" * 70,
            "",
            f"Total combinations: {report.total_combinations}",
            f"Pareto optimal:     {len(report.pareto_frontier)}",
            "",
            "Pareto Optimal Configurations:",
            "-" * 70,
            f"{'Batch':>8} {'Workers':>10} {'Conc':>8} {'Throughput':>14} {'P99(ms)':>10} {'P90(ms)':>10}",
            "-" * 70,
        ]
        for r in report.pareto_frontier:
            lines.append(
                f"{r.config.batch_size:>8} {r.config.workers_per_device:>10} "
                f"{r.config.concurrency:>8} {r.metrics.throughput:>14.2f} "
                f"{r.metrics.latency_ms.p99:>10.3f} {r.metrics.latency_ms.p90:>10.3f}"
            )
        lines.append("-" * 70)
        lines.append("")
        if report.pareto_frontier:
            by_latency = sorted(report.pareto_frontier, key=lambda x: x.metrics.latency_ms.p99)
            bl = by_latency[0]
            lines.append(
                f"Latency-optimal:  Batch={bl.config.batch_size}, "
                f"Workers={bl.config.workers_per_device}, Conc={bl.config.concurrency}"
            )
            by_tput = sorted(report.pareto_frontier, key=lambda x: x.metrics.throughput, reverse=True)
            bt = by_tput[0]
            lines.append(
                f"Throughput-optimal: Batch={bt.config.batch_size}, "
                f"Workers={bt.config.workers_per_device}, Conc={bt.config.concurrency}"
            )
        lines.append("")
        return "\n".join(lines)
