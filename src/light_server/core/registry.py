"""Model registry using process-safe shared state (mp.Manager)."""

from __future__ import annotations

import multiprocessing as mp
import threading
from typing import Any


class ModelRegistry:
    """Process-safe model registry backed by mp.Manager().dict().

    Supports multi-process HTTP workers sharing registry state.
    All operations that read or write shared state go through the
    Manager proxy, which handles inter-process synchronization.
    """

    def __init__(self, manager: Any = None) -> None:
        if manager is None:
            manager = mp.Manager()
        self._manager = manager
        # Shared state across processes
        self._registry: Any = manager.dict()
        self._active_versions: Any = manager.dict()
        self._queues: Any = manager.dict()
        self._worker_queues: Any = manager.dict()
        # Local lock for batch atomic updates on the calling process
        self._lock = threading.Lock()

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state.pop("_lock", None)
        state.pop("_manager", None)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._lock = threading.Lock()

    @staticmethod
    def _key(name: str, version: str) -> str:
        return f"{name}_{version}"

    def register(
        self,
        name: str,
        version: str = "1",
        config: dict[str, Any] | None = None,
        model_type: str = "litapi",
        model_dir: str | None = None,
    ) -> None:
        key = self._key(name, version)
        entry: dict[str, Any] = {
            "name": name,
            "version": version,
            "status": "LOADING",
            "config": config or {},
            "model_type": model_type,
        }
        if model_dir is not None:
            entry["model_dir"] = model_dir
        self._registry[key] = entry

    def set_queue(self, name: str, version: str, queue: Any) -> None:
        self._queues[self._key(name, version)] = queue

    def get_queue(self, name: str, version: str | None = None) -> Any:
        if version is None:
            version = self._active_versions.get(name)
            if version is None:
                return None
        return self._queues.get(self._key(name, version))

    def set_worker_queues(self, name: str, version: str, queues: list[Any]) -> None:
        """Store per-worker request queues for a model version.

        Queues are stored as a tuple (immutable) so they survive
        Manager.dict() serialization.
        """
        self._worker_queues[self._key(name, version)] = tuple(queues)

    def get_worker_queue(self, name: str, version: str, worker_id: int) -> Any:
        """Get a specific worker's request queue."""
        queues = self._worker_queues.get(self._key(name, version))
        if queues is None or worker_id >= len(queues):
            return None
        return queues[worker_id]

    def get_worker_queues(self, name: str, version: str | None = None) -> list[Any] | None:
        """Get all per-worker request queues for a model version."""
        if version is None:
            version = self._active_versions.get(name)
            if version is None:
                return None
        queues = self._worker_queues.get(self._key(name, version))
        if queues is None:
            return None
        return list(queues)

    def set_status(self, name: str, version: str, status: str) -> None:
        key = self._key(name, version)
        entry = self._registry.get(key)
        if entry is not None:
            entry["status"] = status
            # Re-assign to trigger Manager sync
            self._registry[key] = entry

    def update_entry(self, name: str, version: str, **fields: Any) -> bool:
        """Safely update fields on an existing registry entry.

        Returns True if the entry existed and was updated.
        """
        key = self._key(name, version)
        entry = self._registry.get(key)
        if entry is None:
            return False
        entry.update(fields)
        # Re-assign to trigger Manager sync
        self._registry[key] = entry
        return True

    def get(self, name: str, version: str | None = None) -> dict[str, Any] | None:
        if version is None:
            version = self._active_versions.get(name)
            if version is None:
                return None
        entry = self._registry.get(self._key(name, version))
        if entry is None:
            return None
        return dict(entry)

    def remove(self, name: str, version: str) -> None:
        key = self._key(name, version)
        self._registry.pop(key, None)
        self._queues.pop(key, None)
        self._worker_queues.pop(key, None)

    def list_loaded(self) -> list[dict[str, Any]]:
        return [dict(v) for v in list(self._registry.values())]

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        """List all loaded versions for a model."""
        result: list[dict[str, Any]] = []
        prefix = f"{name}_"
        for key in list(self._registry.keys()):
            if key.startswith(prefix):
                result.append(dict(self._registry[key]))
        return result

    def is_ready(self, name: str, version: str | None = None) -> bool:
        if version is None:
            version = self._active_versions.get(name)
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
