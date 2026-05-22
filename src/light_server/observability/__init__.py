"""Observability package for light_server."""

from __future__ import annotations

from light_server.observability.collector import SystemMetrics
from light_server.observability.multiproc import setup_multiproc_metrics

__all__ = ["setup_multiproc_metrics", "SystemMetrics"]
