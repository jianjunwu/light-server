"""Configuration space generation for Model Analyzer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AnalysisConfig:
    """User-defined analysis configuration from model_config.yaml."""

    batch_sizes: list[int]
    workers_per_device: list[int]
    concurrency_levels: list[int]
    duration_per_config: float = 30.0
    warmup_requests: int = 10
    objectives: list[dict[str, Any]] | None = None
    constraints: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisConfig":
        return cls(
            batch_sizes=data.get("batch_sizes", [1]),
            workers_per_device=data.get("workers_per_device", [1]),
            concurrency_levels=data.get("concurrency_levels", [1]),
            duration_per_config=data.get("duration_per_config", 30.0),
            warmup_requests=data.get("warmup_requests", 10),
            objectives=data.get("objectives"),
            constraints=data.get("constraints"),
            payload=data.get("payload"),
        )


@dataclass
class ModelRunConfig:
    """A single configuration point to be benchmarked."""

    batch_size: int
    workers_per_device: int
    concurrency: int

    def to_model_config_override(self) -> dict[str, Any]:
        return {
            "max_batch_size": self.batch_size,
            "workers_per_device": self.workers_per_device,
        }


class ConfigurationSpace:
    """Generate the Cartesian product of all configuration dimensions."""

    def __init__(self, analysis_cfg: AnalysisConfig) -> None:
        self.analysis_cfg = analysis_cfg

    def iterate(self) -> list[ModelRunConfig]:
        """Return all configuration combinations."""
        configs = []
        for bs in self.analysis_cfg.batch_sizes:
            for wpd in self.analysis_cfg.workers_per_device:
                for conc in self.analysis_cfg.concurrency_levels:
                    configs.append(
                        ModelRunConfig(
                            batch_size=bs,
                            workers_per_device=wpd,
                            concurrency=conc,
                        )
                    )
        return configs

    @property
    def total_combinations(self) -> int:
        return (
            len(self.analysis_cfg.batch_sizes)
            * len(self.analysis_cfg.workers_per_device)
            * len(self.analysis_cfg.concurrency_levels)
        )
