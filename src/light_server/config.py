"""YAML configuration loading and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ServerConfig:
    http_port: int = 8000
    grpc_port: int = 8001
    metrics_port: int = 8002
    host: str = "0.0.0.0"
    timeout: float = 30.0
    log_level: str = "info"
    http_workers: int | None = None  # None = auto (max(1, cpu_count() - 1))
    transport: str = "mp"  # "mp" | "zmq"


@dataclass
class GrpcConfig:
    enabled: bool = True
    max_workers: int = 10


@dataclass
class MetricsConfig:
    enabled: bool = True


@dataclass
class LoggingConfig:
    mode: str = "queue"
    level: str = "info"
    format: str = "text"
    output: str | None = None
    info_output: str | None = None
    error_output: str | None = None
    rotation: str = "daily"
    rotate_by: str = "none"  # none | size | time
    max_size: int = 100  # MB
    when: str = "midnight"
    backup_count: int = 7


@dataclass
class ModelRepositoryConfig:
    path: str = "./model_repo"


@dataclass
class ModelConfig:
    """Per-version inference parameters (matches config.yaml)."""

    name: str = ""
    api_path: str = "/predict"
    max_batch_size: int = 1
    batch_timeout: float = 0.0
    stream: bool = False
    bidirectional: bool = False
    continuous_batching: bool = False
    max_sequence_length: int = 2048
    accelerator: str | None = None
    devices: int | str | None = None
    workers_per_device: int | None = None
    max_queue_size: int = 1000


@dataclass
class ModelStrategyConfig:
    name: str = ""
    load_policy: str = "explicit"
    versions_to_load: list[str] = field(default_factory=list)
    default_version: str | None = None
    max_loaded_versions: int | None = None


@dataclass
class OrchestrationConfig:
    control_mode: str = "explicit"
    poll_interval: int = 5
    load_models: list[str] = field(default_factory=list)
    models: list[ModelStrategyConfig] = field(default_factory=list)


@dataclass
class WebUIConfig:
    enabled: bool = True
    report_retention_days: int = 30


@dataclass
class FeaturesConfig:
    timeline: bool = False
    system_overview: bool = True
    custom_metrics: bool = False
    benchmarks: bool = True
    playground: bool = False
    alerts: bool = True
    version_compare: bool = False


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    grpc: GrpcConfig = field(default_factory=GrpcConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    model_repository: ModelRepositoryConfig = field(
        default_factory=ModelRepositoryConfig
    )
    webui: WebUIConfig = field(default_factory=WebUIConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    orchestration: OrchestrationConfig = field(
        default_factory=OrchestrationConfig
    )


def _to_dataclass(data: dict[str, Any], cls: type) -> Any:
    """Convert a dict to a dataclass, ignoring unknown keys."""
    if not data:
        return cls()
    field_names = {f.name for f in cls.__dataclass_fields__.values()}
    kwargs = {k: v for k, v in data.items() if k in field_names}
    return cls(**kwargs)


def load_config(path: str | Path) -> Config:
    """Load configuration from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    config = Config()

    if "server" in raw:
        config.server = _to_dataclass(raw["server"], ServerConfig)
    if "grpc" in raw:
        config.grpc = _to_dataclass(raw["grpc"], GrpcConfig)
    if "metrics" in raw:
        config.metrics = _to_dataclass(raw["metrics"], MetricsConfig)
    if "logging" in raw:
        config.logging = _to_dataclass(raw["logging"], LoggingConfig)
    if "model_repository" in raw:
        config.model_repository = _to_dataclass(
            raw["model_repository"], ModelRepositoryConfig
        )
    if "webui" in raw:
        config.webui = _to_dataclass(raw["webui"], WebUIConfig)
    if "features" in raw:
        config.features = _to_dataclass(raw["features"], FeaturesConfig)

    # Expand environment variables in paths
    config.model_repository.path = os.path.expandvars(
        config.model_repository.path
    )

    return config


def load_orchestration(path: str | Path) -> OrchestrationConfig:
    """Load orchestration configuration from a YAML file."""
    path = Path(path)
    if not path.exists():
        return OrchestrationConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    orch = OrchestrationConfig()

    if "control_mode" in raw:
        orch.control_mode = raw["control_mode"]
    if "poll_interval" in raw:
        orch.poll_interval = raw["poll_interval"]
    if "load_models" in raw:
        orch.load_models = raw["load_models"]
    if "models" in raw:
        orch.models = [
            _to_dataclass(m, ModelStrategyConfig) for m in raw["models"]
        ]

    return orch
