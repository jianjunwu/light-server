"""Tests for TTL response buffer leak prevention."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from light_server.core.response_buffer import TTLResponseBuffer


class TestTTLResponseBuffer:
    def test_set_and_get(self):
        buf = TTLResponseBuffer(ttl_seconds=60.0, max_size=100)
        buf["uid1"] = {"data": "hello"}
        assert buf.get("uid1") == {"data": "hello"}
        assert buf["uid1"] == {"data": "hello"}

    def test_pop_returns_item(self):
        buf = TTLResponseBuffer(ttl_seconds=60.0, max_size=100)
        buf["uid1"] = {"data": "hello"}
        item = buf.pop("uid1")
        assert item == {"data": "hello"}
        assert buf.get("uid1") is None

    def test_pop_with_default(self):
        buf = TTLResponseBuffer(ttl_seconds=60.0, max_size=100)
        item = buf.pop("missing", None)
        assert item is None

    def test_contains_and_len(self):
        buf = TTLResponseBuffer(ttl_seconds=60.0, max_size=100)
        buf["a"] = 1
        buf["b"] = 2
        assert "a" in buf
        assert "z" not in buf
        assert len(buf) == 2

    def test_max_size_evicts_oldest(self):
        buf = TTLResponseBuffer(ttl_seconds=60.0, max_size=3)
        buf["a"] = 1
        time.sleep(0.01)
        buf["b"] = 2
        time.sleep(0.01)
        buf["c"] = 3
        # Now at max size
        assert len(buf) == 3
        time.sleep(0.01)
        buf["d"] = 4
        # Oldest (a) should be evicted
        assert len(buf) == 3
        assert "a" not in buf
        assert "d" in buf

    def test_expire_stale_removes_old_entries(self):
        buf = TTLResponseBuffer(ttl_seconds=0.5, max_size=100)
        buf["a"] = 1
        time.sleep(0.6)
        buf._expire_stale()
        assert "a" not in buf
        assert len(buf) == 0

    def test_expire_stale_keeps_fresh_entries(self):
        buf = TTLResponseBuffer(ttl_seconds=10.0, max_size=100)
        buf["a"] = 1
        buf._expire_stale()
        assert "a" in buf

    def test_cleanup_loop_runs_in_background(self):
        buf = TTLResponseBuffer(
            ttl_seconds=0.3, max_size=100, cleanup_interval_seconds=0.1
        )
        buf["a"] = 1
        buf.start()
        time.sleep(0.5)
        buf.stop()
        assert "a" not in buf

    def test_thread_safety_race(self):
        import threading
        buf = TTLResponseBuffer(ttl_seconds=60.0, max_size=1000)
        errors = []

        def writer():
            try:
                for i in range(100):
                    buf[f"uid-{i}"] = i
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(100):
                    buf.get(f"uid-{i}")
                    buf.pop(f"uid-{i}", None)
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(5):
            t = threading.Thread(target=writer)
            threads.append(t)
            t.start()
        for _ in range(5):
            t = threading.Thread(target=reader)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert not errors
