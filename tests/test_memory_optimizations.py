"""Tests for memory optimizations (atomic uid, counter cleanup)."""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry


class TestAtomicUidCounter:
    """Verify atomic integer uid generation and cleanup."""

    @pytest.fixture
    def manager(self, tmp_path: Path):
        registry = ModelRegistry()
        return ModelManager(
            repo_path=tmp_path,
            registry=registry,
        )

    def test_infer_generates_sequential_uids(self, manager: ModelManager):
        """Uids for the same model should have sequential numbers."""
        registry = manager.registry
        registry.register("test_model", "1")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        # Need a queue for infer() to work
        mock_queue = MagicMock()
        registry.set_queue("test_model", "1", mock_queue)

        uids = [manager.infer("test_model", {"input": i}) for i in range(5)]

        # Uid format: {name}_{version}-{seq}-{hex}  (key-seq-hex)
        seqs = [int(uid.split("-")[1]) for uid in uids]
        assert seqs == [0, 1, 2, 3, 4]

    def test_infer_unique_across_models(self, manager: ModelManager):
        """Different models have independent counters, uids remain unique."""
        registry = manager.registry
        for name in ("model_a", "model_b"):
            registry.register(name, "1")
            registry.set_status(name, "1", "READY")
            registry.activate_version(name, "1")
            registry.set_queue(name, "1", MagicMock())

        uid_a = manager.infer("model_a", {"input": 1})
        uid_b = manager.infer("model_b", {"input": 2})

        # Different models → different counters, both start at 0
        assert uid_a != uid_b
        assert uid_a.split("-")[1] == "0"
        assert uid_b.split("-")[1] == "0"

    def test_infer_uid_format(self, manager: ModelManager):
        """Uid format: {name}_{version}-{seq}-{hex_timestamp_suffix}."""
        registry = manager.registry
        registry.register("my_model", "v2")
        registry.set_status("my_model", "v2", "READY")
        registry.activate_version("my_model", "v2")
        registry.set_queue("my_model", "v2", MagicMock())

        uid = manager.infer("my_model", {"input": 1})
        # Format: {key}-{seq}-{hex} where key = name_version
        parts = uid.split("-")

        assert len(parts) == 3
        assert parts[0] == "my_model_v2"  # key part
        assert parts[1] == "0"  # first sequence number
        # last part is 8-char hex
        assert len(parts[2]) == 8
        int(parts[2], 16)  # valid hex

    def test_unload_cleans_uid_counter(self, manager: ModelManager):
        """After unload, the uid counter for that model should be gone."""
        registry = manager.registry
        registry.register("test_model", "1")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        registry.set_queue("test_model", "1", MagicMock())

        # Generate a uid to create the counter
        manager.infer("test_model", {"input": 1})
        key = "test_model_1"
        assert key in manager._uid_counters

        # Setup worker for unload
        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False
        manager._workers[key] = [mock_worker]
        manager._litapi_instances[key] = MagicMock()
        manager._workers_setup_status[key] = mp.Manager().dict()

        manager.unload("test_model", "1")
        assert key not in manager._uid_counters

    def test_atomic_counter_faster_than_uuid(self):
        """Atomic counter core logic should be measurably faster than uuid.uuid4()."""
        import itertools
        import time
        import uuid

        counter = itertools.count()

        # Warm up
        for _ in range(100):
            next(counter)
            str(uuid.uuid4())

        # Atomic counter timing
        start = time.perf_counter()
        for _ in range(50000):
            f"req-{next(counter)}-{0xFFFFFFFF:08x}"
        atomic_time = time.perf_counter() - start

        # uuid4 timing
        start = time.perf_counter()
        for _ in range(50000):
            str(uuid.uuid4())
        uuid_time = time.perf_counter() - start

        # Atomic counter should be at least 3x faster
        assert atomic_time < uuid_time / 3, (
            f"Atomic uid ({atomic_time:.4f}s) not faster than uuid4 ({uuid_time:.4f}s)"
        )
