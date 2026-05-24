"""Tests for TTLResponseBuffer."""

from __future__ import annotations

import time

import pytest

from light_server.core.response_buffer import TTLResponseBuffer


# ------------------------------------------------------------------
# Basic CRUD
# ------------------------------------------------------------------


def test_set_and_get():
    buf = TTLResponseBuffer()
    buf["uid-1"] = {"result": 42}
    assert buf["uid-1"] == {"result": 42}


def test_get_with_default():
    buf = TTLResponseBuffer()
    assert buf.get("missing") is None
    assert buf.get("missing", "fallback") == "fallback"


def test_get_existing_no_default():
    buf = TTLResponseBuffer()
    buf["uid-1"] = "value"
    assert buf.get("uid-1") == "value"


def test_contains():
    buf = TTLResponseBuffer()
    buf["uid-1"] = "x"
    assert "uid-1" in buf
    assert "uid-2" not in buf


def test_len():
    buf = TTLResponseBuffer()
    assert len(buf) == 0
    buf["uid-1"] = "a"
    buf["uid-2"] = "b"
    assert len(buf) == 2


def test_pop_returns_value():
    buf = TTLResponseBuffer()
    buf["uid-1"] = "value"
    assert buf.pop("uid-1") == "value"
    assert "uid-1" not in buf


def test_pop_missing_raises_keyerror():
    buf = TTLResponseBuffer()
    with pytest.raises(KeyError):
        buf.pop("missing")


def test_pop_missing_with_default():
    buf = TTLResponseBuffer()
    assert buf.pop("missing", "default") == "default"


def test_overwrite_existing():
    buf = TTLResponseBuffer()
    buf["uid-1"] = "first"
    buf["uid-1"] = "second"
    assert buf["uid-1"] == "second"
    assert len(buf) == 1


# ------------------------------------------------------------------
# Max size eviction
# ------------------------------------------------------------------


def test_max_size_evicts_oldest():
    buf = TTLResponseBuffer(max_size=2)
    buf["uid-1"] = "a"
    buf["uid-2"] = "b"
    buf["uid-3"] = "c"

    assert len(buf) == 2
    assert "uid-1" not in buf  # oldest evicted
    assert "uid-2" in buf
    assert "uid-3" in buf


def test_max_size_zero():
    """max_size=0 means any insertion immediately evicts itself."""
    buf = TTLResponseBuffer(max_size=0)
    buf["uid-1"] = "a"
    assert len(buf) == 0


def test_max_size_one():
    buf = TTLResponseBuffer(max_size=1)
    buf["uid-1"] = "a"
    buf["uid-2"] = "b"
    assert len(buf) == 1
    assert "uid-1" not in buf
    assert "uid-2" in buf


# ------------------------------------------------------------------
# TTL expiration
# ------------------------------------------------------------------


def test_ttl_expiration():
    """Entries older than ttl should be expired by cleanup."""
    buf = TTLResponseBuffer(ttl_seconds=0.05, cleanup_interval_seconds=0.02)
    buf.start()

    buf["uid-1"] = "a"
    assert "uid-1" in buf

    # Wait for TTL + cleanup interval
    time.sleep(0.1)
    assert "uid-1" not in buf

    buf.stop()


def test_ttl_keeps_fresh():
    """Fresh entries should not be expired."""
    buf = TTLResponseBuffer(ttl_seconds=0.5, cleanup_interval_seconds=0.05)
    buf.start()

    buf["uid-1"] = "a"
    time.sleep(0.1)
    assert "uid-1" in buf

    buf.stop()


def test_ttl_size_limit_combo():
    """Both TTL and size limit work together: expired + excess both removed."""
    buf = TTLResponseBuffer(ttl_seconds=0.05, max_size=10, cleanup_interval_seconds=0.02)
    buf.start()

    buf["uid-1"] = "a"
    buf["uid-2"] = "b"
    time.sleep(0.1)
    buf["uid-3"] = "c"

    # uid-1 and uid-2 expired, uid-3 fresh
    assert "uid-1" not in buf
    assert "uid-2" not in buf
    assert "uid-3" in buf

    buf.stop()


def test_cleanup_evicts_oldest_when_over_size():
    """When buffer is over max_size during cleanup, oldest entries are removed."""
    buf = TTLResponseBuffer(ttl_seconds=10, max_size=2, cleanup_interval_seconds=0.02)
    buf.start()

    buf["uid-1"] = "a"
    time.sleep(0.01)
    buf["uid-2"] = "b"
    time.sleep(0.01)
    buf["uid-3"] = "c"

    # Manually trigger cleanup to evict oldest due to size
    buf._expire_stale()
    assert len(buf) == 2
    assert "uid-1" not in buf

    buf.stop()


# ------------------------------------------------------------------
# Lifecycle
# ------------------------------------------------------------------


def test_start_and_stop():
    buf = TTLResponseBuffer()
    buf.start()
    assert buf._cleanup_thread is not None
    assert buf._cleanup_thread.is_alive()

    buf.stop()
    assert not buf._cleanup_thread.is_alive()


def test_stop_idempotent():
    buf = TTLResponseBuffer()
    buf.start()
    buf.stop()
    buf.stop()  # should not crash


def test_multiple_start_calls():
    """Multiple start() calls should replace the cleanup thread."""
    buf = TTLResponseBuffer()
    buf.start()
    first_thread = buf._cleanup_thread
    buf.start()
    second_thread = buf._cleanup_thread
    # Thread object should be replaced
    assert second_thread is not None
    buf.stop()


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


def test_getitem_missing_raises_keyerror():
    buf = TTLResponseBuffer()
    with pytest.raises(KeyError):
        _ = buf["missing"]


def test_operations_without_start():
    """Buffer works without explicitly starting cleanup thread."""
    buf = TTLResponseBuffer()
    buf["uid-1"] = "a"
    assert buf["uid-1"] == "a"
    assert len(buf) == 1
