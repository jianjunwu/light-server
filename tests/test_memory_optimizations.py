"""Tests for memory optimizations (atomic uid, counter cleanup)."""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry


class FakeQueue:
    """Picklable fake queue for testing."""

    def __init__(self, maxsize: int = 0) -> None:
        self._items: list[Any] = []
        self._maxsize = maxsize

    def put_nowait(self, item: Any) -> None:
        if self._maxsize and len(self._items) >= self._maxsize:
            raise Exception("Queue full")
        self._items.append(item)

    def put(self, item: Any, timeout: float | None = None) -> None:
        self.put_nowait(item)

    def get(self) -> Any:
        return self._items.pop(0)

    def qsize(self) -> int:
        return len(self._items)


class TestAtomicUidCounter:
    """Verify uuid-based uid generation (process-safe, no locks)."""

    @pytest.fixture
    def manager(self, tmp_path: Path):
        registry = ModelRegistry()
        return ModelManager(
            repo_path=tmp_path,
            registry=registry,
        )

    def test_infer_generates_unique_uids(self, manager: ModelManager):
        """Uids for the same model should all be unique."""
        registry = manager.registry
        registry.register("test_model", "1")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        # Need a queue for infer() to work
        fake_queue = FakeQueue()
        registry.set_queue("test_model", "1", fake_queue)

        uids = [manager.infer("test_model", {"input": i}) for i in range(20)]

        assert len(set(uids)) == len(uids)

    def test_infer_unique_across_models(self, manager: ModelManager):
        """Different models generate independent unique uids."""
        registry = manager.registry
        for name in ("model_a", "model_b"):
            registry.register(name, "1")
            registry.set_status(name, "1", "READY")
            registry.activate_version(name, "1")
            registry.set_queue(name, "1", FakeQueue())

        uid_a = manager.infer("model_a", {"input": 1})
        uid_b = manager.infer("model_b", {"input": 2})

        assert uid_a != uid_b

    def test_infer_uid_format(self, manager: ModelManager):
        """Uid format: {name}_{version}-{uuid}-{timestamp}."""
        registry = manager.registry
        registry.register("my_model", "v2")
        registry.set_status("my_model", "v2", "READY")
        registry.activate_version("my_model", "v2")
        registry.set_queue("my_model", "v2", FakeQueue())

        uid = manager.infer("my_model", {"input": 1})
        # Format: {name}_{version}-{uuid}-{timestamp}
        parts = uid.split("-")

        assert len(parts) == 3
        assert parts[0] == "my_model_v2"  # key part
        # parts[1] is uuid (32 hex chars)
        assert len(parts[1]) == 32
        # parts[2] is monotonic_ns (integer)
        assert parts[2].isdigit()

    def test_no_uid_counters_after_infer(self, manager: ModelManager):
        """With uuid-based uids, no per-model counters are created."""
        registry = manager.registry
        registry.register("test_model", "1")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        registry.set_queue("test_model", "1", FakeQueue())

        # Generate a uid - should not create any counter state
        manager.infer("test_model", {"input": 1})
        assert not hasattr(manager, "_uid_counters") or not manager._uid_counters

    def test_unload_no_uid_counter_cleanup_needed(self, manager: ModelManager):
        """After unload, no uid counter cleanup is needed (none exists)."""
        registry = manager.registry
        registry.register("test_model", "1")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        registry.set_queue("test_model", "1", FakeQueue())

        # Generate a uid
        manager.infer("test_model", {"input": 1})
        key = "test_model_1"

        # Setup worker for unload
        class FakeWorker:
            def is_alive(self):
                return False
        class FakeLitAPI:
            pass
        manager._workers[key] = [FakeWorker()]
        manager._litapi_instances[key] = FakeLitAPI()
        manager._workers_setup_status[key] = mp.Manager().dict()

        manager.unload("test_model", "1")
        # No _uid_counters to check - they don't exist in the new design
        assert key not in getattr(manager, "_workers", {})
