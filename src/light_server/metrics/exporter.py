"""Prometheus metrics HTTP endpoint."""

from __future__ import annotations

import threading
from typing import Any

from prometheus_client import start_http_server


def start_metrics_server(host: str = "0.0.0.0", port: int = 8002) -> Any:
    """Start a Prometheus metrics HTTP server in a background thread."""
    server, thread = start_http_server(port, addr=host)
    return server
