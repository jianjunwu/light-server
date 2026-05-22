"""Prometheus multiprocess mode setup for multi-worker metrics aggregation."""

from __future__ import annotations

import glob
import os
import tempfile
from typing import Any

from prometheus_client import CollectorRegistry, multiprocess


def setup_multiproc_metrics(clean: bool = True) -> tuple[CollectorRegistry, str]:
    """Setup prometheus multiprocess mode.

    Returns (registry, metrics_dir) where metrics_dir is the directory
    used for inter-process metric file storage.
    """
    metrics_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not metrics_dir:
        metrics_dir = tempfile.mkdtemp(prefix="prometheus_multiproc_")
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = metrics_dir

    if clean:
        for f in glob.glob(os.path.join(metrics_dir, "*.db")):
            try:
                os.remove(f)
            except OSError:
                pass

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return registry, metrics_dir
