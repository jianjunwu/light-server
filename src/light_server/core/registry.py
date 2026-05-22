"""Model registry using multiprocessing-safe shared state."""

from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelEntry:
    """Information about a loaded model."""
    name: str
    version: str = "1"
    status: str = "LOADING"  # LOADING, READY, UNLOADING, ERROR
    config: dict[str, Any] = field(default_factory=dict)
    # request_queue is set after init; not stored in registry dict directly
    # because mp.Manager().dict() values must be picklable
    # We store queue references separately in the manager


class ModelRegistry:
    """Thread/process-safe model registry backed by mp.Manager().dict()."""

    def __init__(self, manager: mp.Manager | None = None):
        self._manager = manager or mp.Manager()
        self._registry: dict[str, dict[str, Any]] = self._manager.dict()
        self._queues: dict[str, Any] = self._manager.dict()

    def register(self, name: str, version: str = "1", config: dict[str, Any] | None = None) -> None:
        self._registry[name] = {
            "name": name,
            "version": version,
            "status": "LOADING",
            "config": config or {},
        }

    def set_queue(self, name: str, queue: Any) -> None:
        self._queues[name] = queue

    def get_queue(self, name: str) -> Any:
        return self._queues.get(name)

    def set_status(self, name: str, status: str) -> None:
        if name in self._registry:
            entry = dict(self._registry[name])
            entry["status"] = status
            self._registry[name] = entry

    def get(self, name: str) -> dict[str, Any] | None:
        return self._registry.get(name)

    def remove(self, name: str) -> None:
        self._registry.pop(name, None)
        self._queues.pop(name, None)

    def list_loaded(self) -> list[dict[str, Any]]:
        return [dict(v) for v in self._registry.values()]

    def is_ready(self, name: str) -> bool:
        entry = self._registry.get(name)
        return entry is not None and entry.get("status") == "READY"
