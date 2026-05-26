"""Light Server - Triton-style deployment server built on LitServe."""

import importlib.metadata

from light_server.api import LitAPI
from light_server.config import (
    Config,
    GrpcConfig,
    LoggingConfig,
    MetricsConfig,
    ModelConfig,
    ModelRepositoryConfig,
    ServerConfig,
    WebUIConfig,
    load_config,
)
from light_server.core.server import LightServer

try:
    __version__ = importlib.metadata.version("light-server")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.4.2"

__all__ = [
    "LitAPI",
    "Config",
    "ServerConfig",
    "GrpcConfig",
    "MetricsConfig",
    "LoggingConfig",
    "ModelRepositoryConfig",
    "ModelConfig",
    "WebUIConfig",
    "load_config",
    "LightServer",
]
