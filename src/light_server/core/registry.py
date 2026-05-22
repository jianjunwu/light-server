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
        self._active_versions: dict[str, str] = self._manager.dict()

    @staticmethod
    def _key(name: str, version: str) -> str:
        return f"{name}_{version}"

    def register(self, name: str, version: str = "1", config: dict[str, Any] | None = None, model_type: str = "litapi") -> None:
        key = self._key(name, version)
        self._registry[key] = {
            "name": name,
            "version": version,
            "status": "LOADING",
            "config": config or {},
            "model_type": model_type,
        }

    def set_queue(self, name: str, version: str, queue: Any) -> None:
        self._queues[self._key(name, version)] = queue

    def get_queue(self, name: str, version: str | None = None) -> Any:
        if version is None:
            version = self.get_active_version(name)
            if version is None:
                return None
        return self._queues.get(self._key(name, version))

    def set_status(self, name: str, version: str, status: str) -> None:
        key = self._key(name, version)
        if key in self._registry:
            entry = dict(self._registry[key])
            entry["status"] = status
            self._registry[key] = entry

    def get(self, name: str, version: str | None = None) -> dict[str, Any] | None:
        if version is None:
            version = self.get_active_version(name)
            if version is None:
                return None
        return self._registry.get(self._key(name, version))

    def remove(self, name: str, version: str) -> None:
        key = self._key(name, version)
        self._registry.pop(key, None)
        self._queues.pop(key, None)

    def list_loaded(self) -> list[dict[str, Any]]:
        return [dict(v) for v in self._registry.values()]

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        """List all loaded versions for a model."""
        result = []
        prefix = f"{name}_"
        for key, entry in self._registry.items():
            if key.startswith(prefix):
                result.append(dict(entry))
        return result

    def is_ready(self, name: str, version: str | None = None) -> bool:
        if version is None:
            version = self.get_active_version(name)
            if version is None:
                return False
        entry = self._registry.get(self._key(name, version))
        return entry is not None and entry.get("status") == "READY"

    def activate_version(self, name: str, version: str) -> bool:
        """Set the active version for a model. Returns True if version exists and is ready."""
        key = self._key(name, version)
        entry = self._registry.get(key)
        if entry is None or entry.get("status") != "READY":
            return False
        self._active_versions[name] = version
        return True

    def get_active_version(self, name: str) -> str | None:
        return self._active_versions.get(name)

    def deactivate(self, name: str) -> None:
        self._active_versions.pop(name, None)
