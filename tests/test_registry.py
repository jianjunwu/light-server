"""Tests for ModelRegistry."""

from __future__ import annotations

import threading

import pytest

from light_server.core.registry import ModelRegistry


# ------------------------------------------------------------------
# Basic CRUD
# ------------------------------------------------------------------


def test_register_and_get():
    registry = ModelRegistry()
    registry.register("m1", version="1", config={"batch": 4})

    entry = registry.get("m1", "1")
    assert entry is not None
    assert entry["name"] == "m1"
    assert entry["version"] == "1"
    assert entry["status"] == "LOADING"
    assert entry["config"] == {"batch": 4}
    assert entry["model_type"] == "litapi"


def test_get_nonexistent():
    registry = ModelRegistry()
    assert registry.get("missing", "1") is None


def test_set_status():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.set_status("m1", "1", "READY")

    entry = registry.get("m1", "1")
    assert entry["status"] == "READY"


def test_set_status_nonexistent():
    """Setting status on a non-existent model should not crash."""
    registry = ModelRegistry()
    registry.set_status("missing", "1", "READY")  # no-op
    assert registry.get("missing", "1") is None


def test_remove():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    assert registry.get("m1", "1") is not None

    registry.remove("m1", "1")
    assert registry.get("m1", "1") is None


def test_remove_idempotent():
    """Removing a non-existent model should not crash."""
    registry = ModelRegistry()
    registry.remove("missing", "1")  # no-op


# ------------------------------------------------------------------
# list_loaded
# ------------------------------------------------------------------


def test_list_loaded_empty():
    registry = ModelRegistry()
    assert registry.list_loaded() == []


def test_list_loaded_returns_copies():
    """list_loaded should return copies so callers cannot mutate internal state."""
    registry = ModelRegistry()
    registry.register("m1", version="1", config={"a": 1})

    loaded = registry.list_loaded()
    assert len(loaded) == 1
    loaded[0]["status"] = "TAMPERED"

    # Internal state should be unchanged
    assert registry.get("m1", "1")["status"] == "LOADING"


def test_list_loaded_multiple_models():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.register("m2", version="1")
    registry.register("m1", version="2")

    loaded = registry.list_loaded()
    assert len(loaded) == 3
    names = {e["name"] for e in loaded}
    assert names == {"m1", "m2"}


# ------------------------------------------------------------------
# Queue management
# ------------------------------------------------------------------


def test_set_and_get_queue():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    fake_queue = object()
    registry.set_queue("m1", "1", fake_queue)

    assert registry.get_queue("m1", "1") is fake_queue


def test_get_queue_nonexistent():
    registry = ModelRegistry()
    assert registry.get_queue("m1", "1") is None


def test_set_and_get_worker_queues():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    q1, q2 = object(), object()
    registry.set_worker_queues("m1", "1", [q1, q2])

    assert registry.get_worker_queue("m1", "1", 0) is q1
    assert registry.get_worker_queue("m1", "1", 1) is q2
    assert registry.get_worker_queues("m1", "1") == [q1, q2]


def test_get_worker_queue_out_of_range():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.set_worker_queues("m1", "1", [object()])
    assert registry.get_worker_queue("m1", "1", 5) is None


def test_get_worker_queue_no_queues():
    registry = ModelRegistry()
    assert registry.get_worker_queue("m1", "1", 0) is None


def test_remove_cleans_queues():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.set_queue("m1", "1", object())
    registry.set_worker_queues("m1", "1", [object()])

    registry.remove("m1", "1")
    assert registry.get_queue("m1", "1") is None
    assert registry.get_worker_queues("m1", "1") is None


# ------------------------------------------------------------------
# Version activation
# ------------------------------------------------------------------


def test_activate_version():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.set_status("m1", "1", "READY")

    assert registry.activate_version("m1", "1") is True
    assert registry.get_active_version("m1") == "1"


def test_activate_version_not_ready():
    """Cannot activate a version that is not in READY state."""
    registry = ModelRegistry()
    registry.register("m1", version="1")  # status is LOADING

    assert registry.activate_version("m1", "1") is False
    assert registry.get_active_version("m1") is None


def test_activate_version_nonexistent():
    registry = ModelRegistry()
    assert registry.activate_version("m1", "1") is False


def test_deactivate():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.set_status("m1", "1", "READY")
    registry.activate_version("m1", "1")
    assert registry.get_active_version("m1") == "1"

    registry.deactivate("m1")
    assert registry.get_active_version("m1") is None


def test_deactivate_idempotent():
    registry = ModelRegistry()
    registry.deactivate("m1")  # no-op
    assert registry.get_active_version("m1") is None


# ------------------------------------------------------------------
# is_ready
# ------------------------------------------------------------------


def test_is_ready_true():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.set_status("m1", "1", "READY")
    assert registry.is_ready("m1", "1") is True


def test_is_ready_loading():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    assert registry.is_ready("m1", "1") is False


def test_is_ready_nonexistent():
    registry = ModelRegistry()
    assert registry.is_ready("m1", "1") is False


def test_is_ready_uses_active_version():
    """When version is None, is_ready should use the active version."""
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.register("m1", version="2")
    registry.set_status("m1", "1", "READY")
    registry.set_status("m1", "2", "READY")
    registry.activate_version("m1", "2")

    assert registry.is_ready("m1") is True
    registry.deactivate("m1")
    assert registry.is_ready("m1") is False


# ------------------------------------------------------------------
# get with active version fallback
# ------------------------------------------------------------------


def test_get_uses_active_version():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.register("m1", version="2")
    registry.set_status("m1", "2", "READY")
    registry.activate_version("m1", "2")

    entry = registry.get("m1")
    assert entry is not None
    assert entry["version"] == "2"


def test_get_no_active_version():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    assert registry.get("m1") is None


def test_get_queue_uses_active_version():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.set_status("m1", "1", "READY")
    registry.activate_version("m1", "1")
    fake_queue = object()
    registry.set_queue("m1", "1", fake_queue)

    assert registry.get_queue("m1") is fake_queue


def test_get_worker_queues_uses_active_version():
    registry = ModelRegistry()
    registry.register("m1", version="1")
    registry.set_status("m1", "1", "READY")
    registry.activate_version("m1", "1")
    queues = [object()]
    registry.set_worker_queues("m1", "1", queues)

    assert registry.get_worker_queues("m1") == queues


# ------------------------------------------------------------------
# list_versions
# ------------------------------------------------------------------


def test_list_versions():
    registry = ModelRegistry()
    registry.register("m1", version="1", config={"a": 1})
    registry.register("m1", version="2", config={"a": 2})
    registry.register("m2", version="1")

    versions = registry.list_versions("m1")
    assert len(versions) == 2
    configs = {v["config"]["a"] for v in versions}
    assert configs == {1, 2}


def test_list_versions_no_match():
    registry = ModelRegistry()
    assert registry.list_versions("missing") == []


# ------------------------------------------------------------------
# Thread safety
# ------------------------------------------------------------------


def test_concurrent_register_and_remove():
    """Concurrent register/remove should not corrupt internal state."""
    registry = ModelRegistry()
    errors = []

    def worker(name: str) -> None:
        try:
            for i in range(50):
                registry.register(name, version=str(i))
                registry.set_status(name, str(i), "READY")
                registry.remove(name, str(i))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(f"m{j}",)) for j in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert registry.list_loaded() == []


def test_concurrent_read_and_write():
    """Concurrent reads during writes should not crash."""
    registry = ModelRegistry()
    registry.register("m1", version="1")
    errors = []

    def writer() -> None:
        try:
            for _ in range(100):
                registry.set_status("m1", "1", "READY")
                registry.set_status("m1", "1", "LOADING")
        except Exception as e:
            errors.append(e)

    def reader() -> None:
        try:
            for _ in range(100):
                _ = registry.get("m1", "1")
                _ = registry.is_ready("m1", "1")
                _ = registry.list_loaded()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
