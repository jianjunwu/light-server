"""Model registry using thread-safe in-process state (no mp.Manager overhead)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelEntry:
    """Information about a loaded model."""

    name: str
    version: str = "1"
    status: str = "LOADING"  # LOADING, READY, UNLOADING, ERROR
    config: dict[str, Any] = field(default_factory=dict)


class ModelRegistry:
    """Thread-safe model registry backed by plain dict + threading.Lock.

    Since uvicorn runs with workers=1, the HTTP handler and ModelManager
    live in the same process.  A threading.Lock is sufficient and avoids
    the IPC overhead of mp.Manager().dict().
    """

    def __init__(self, manager: Any = None) -> None:
        # manager is accepted for backward compatibility but no longer used
        # since registry state is in-process only (HTTP handler + ModelManager
        # live in the same process when uvicorn workers=1).
        self._lock = threading.Lock()
        self._registry: dict[str, dict[str, Any]] = {}
        self._queues: dict[str, Any] = {}
        self._worker_queues: dict[str, list[Any]] = {}  # model_key -> list of per-worker queues
        self._active_versions: dict[str, str] = {}

    @staticmethod
    def _key(name: str, version: str) -> str:
        return f"{name}_{version}"

    def register(self, name: str, version: str = "1", config: dict[str, Any] | None = None, model_type: str = "litapi") -> None:
        key = self._key(name, version)
        with self._lock:
            self._registry[key] = {
                "name": name,
                "version": version,
                "status": "LOADING",
                "config": config or {},
                "model_type": model_type,
            }

    def set_queue(self, name: str, version: str, queue: Any) -> None:
        with self._lock:
            self._queues[self._key(name, version)] = queue

    def get_queue(self, name: str, version: str | None = None) -> Any:
        with self._lock:
            if version is None:
                version = self._active_versions.get(name)
                if version is None:
                    return None
            return self._queues.get(self._key(name, version))

    def set_worker_queues(self, name: str, version: str, queues: list[Any]) -> None:
        """Store per-worker request queues for a model version."""
        with self._lock:
            self._worker_queues[self._key(name, version)] = queues

    def get_worker_queue(self, name: str, version: str, worker_id: int) -> Any:
        """Get a specific worker's request queue."""
        with self._lock:
            queues = self._worker_queues.get(self._key(name, version))
            if queues is None or worker_id >= len(queues):
                return None
            return queues[worker_id]

    def get_worker_queues(self, name: str, version: str | None = None) -> list[Any] | None:
        """Get all per-worker request queues for a model version."""
        with self._lock:
            if version is None:
                version = self._active_versions.get(name)
                if version is None:
                    return None
            return self._worker_queues.get(self._key(name, version))

    def set_status(self, name: str, version: str, status: str) -> None:
        key = self._key(name, version)
        with self._lock:
            entry = self._registry.get(key)
            if entry is not None:
                entry["status"] = status

    def update_entry(self, name: str, version: str, **fields: Any) -> bool:
        """Safely update fields on an existing registry entry.

        Returns True if the entry existed and was updated.
        """
        key = self._key(name, version)
        with self._lock:
            entry = self._registry.get(key)
            if entry is None:
                return False
            entry.update(fields)
            return True

    def get(self, name: str, version: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            if version is None:
                version = self._active_versions.get(name)
                if version is None:
                    return None
            return self._registry.get(self._key(name, version))

    def remove(self, name: str, version: str) -> None:
        key = self._key(name, version)
        with self._lock:
            self._registry.pop(key, None)
            self._queues.pop(key, None)
            self._worker_queues.pop(key, None)

    def list_loaded(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._registry.values()]

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        """List all loaded versions for a model."""
        with self._lock:
            result = []
            prefix = f"{name}_"
            for key, entry in self._registry.items():
                if key.startswith(prefix):
                    result.append(dict(entry))
            return result

    def is_ready(self, name: str, version: str | None = None) -> bool:
        with self._lock:
            if version is None:
                version = self._active_versions.get(name)
                if version is None:
                    return False
            entry = self._registry.get(self._key(name, version))
            return entry is not None and entry.get("status") == "READY"

    def activate_version(self, name: str, version: str) -> bool:
        """Set the active version for a model. Returns True if version exists and is ready."""
        key = self._key(name, version)
        with self._lock:
            entry = self._registry.get(key)
            if entry is None or entry.get("status") != "READY":
                return False
            self._active_versions[name] = version
            return True

    def get_active_version(self, name: str) -> str | None:
        with self._lock:
            return self._active_versions.get(name)

    def deactivate(self, name: str) -> None:
        with self._lock:
            self._active_versions.pop(name, None)
