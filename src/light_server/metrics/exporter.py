"""Prometheus metrics HTTP endpoint."""

from __future__ import annotations

from typing import Any

from prometheus_client import start_http_server
from prometheus_client.core import CollectorRegistry


def start_metrics_server(
    host: str = "0.0.0.0",
    port: int = 8002,
    registry: CollectorRegistry | None = None,
) -> Any:
    """Start a Prometheus metrics HTTP server in a background thread."""
    if registry is None:
        from prometheus_client import REGISTRY
        registry = REGISTRY
    server, thread = start_http_server(port, addr=host, registry=registry)
    return server
