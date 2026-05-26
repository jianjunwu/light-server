"""Prometheus multiprocess mode setup for multi-worker metrics aggregation."""

from __future__ import annotations

import glob
import os
import tempfile
from typing import Any

from prometheus_client import CollectorRegistry, multiprocess


def setup_multiproc_metrics(clean: bool = True) -> tuple[CollectorRegistry, str, bool]:
    """Setup prometheus multiprocess mode.

    Returns (registry, metrics_dir, created_by_us) where metrics_dir is the
    directory used for inter-process metric file storage, and created_by_us
    is True when the function created a temporary directory itself.
    """
    metrics_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    created_by_us = False
    if not metrics_dir:
        metrics_dir = tempfile.mkdtemp(prefix="prometheus_multiproc_")
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = metrics_dir
        created_by_us = True

    if clean:
        for f in glob.glob(os.path.join(metrics_dir, "*.db")):
            try:
                os.remove(f)
            except OSError:
                pass

    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return registry, metrics_dir, created_by_us
