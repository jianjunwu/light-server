"""Tests for AdaptiveBatchedLoop smart batching strategies."""

from __future__ import annotations

import threading
import time
from queue import Empty, Queue
from typing import Any
from unittest.mock import MagicMock

import pytest

from light_server.core.loops import AdaptiveBatchedLoop
from litserve.loops.base import _SENTINEL_VALUE, _StopLoopError


class _FakeLitAPI:
    """Minimal fake LitAPI for loop testing."""

    def __init__(self, max_batch_size: int = 4, batch_timeout: float = 0.01, request_timeout: float = -1):
        self.max_batch_size = max_batch_size
        self.batch_timeout = batch_timeout
        self.request_timeout = request_timeout
        self.stream = False


class _FakeTransport:
    """Minimal fake transport."""

    def __init__(self):
        self.messages: list[tuple[Any, ...]] = []

    def put(self, msg: tuple[Any, ...]) -> None:
        self.messages.append(msg)


class TestAdaptiveBatchedLoop:
    """Verify adaptive batching behaviour across load levels."""

    @pytest.fixture
    def loop(self):
        return AdaptiveBatchedLoop()

    @pytest.fixture
    def lit_api(self):
        return _FakeLitAPI(max_batch_size=4, batch_timeout=0.01)

    @pytest.fixture
    def transport(self):
        return _FakeTransport()

    # ------------------------------------------------------------------
    # Step helpers: enqueue requests with fake data shape
    # ------------------------------------------------------------------
    @staticmethod
    def _enqueue(queue: Queue, count: int, delay_between: float = 0.0) -> None:
        """Put *count* fake requests onto the queue."""
        for i in range(count):
            queue.put((0, f"uid-{i}", time.monotonic(), {"idx": i}))
            if delay_between:
                time.sleep(delay_between)

    # ==================================================================
    # 1. High load: batch fills immediately → zero extra wait
    # ==================================================================
    def test_high_load_returns_immediately_when_batch_full(self, loop, lit_api, transport):
        """When enough requests are already queued, return at once."""
        q = Queue()
        self._enqueue(q, 10)  # more than max_batch_size

        start = time.monotonic()
        payloads, timed_out = loop.get_batch_requests(lit_api, q, transport)
        elapsed = time.monotonic() - start

        # Should have grabbed exactly max_batch_size (4)
        assert len(payloads) == lit_api.max_batch_size
        # Should be essentially instantaneous (< 1ms)
        assert elapsed < 0.001
        assert timed_out == []

    # ==================================================================
    # 2. Low load: single request → zero wait
    # ==================================================================
    def test_low_load_single_request_no_wait(self, loop, lit_api, transport):
        """With only one request queued, return immediately without waiting."""
        q = Queue()
        self._enqueue(q, 1)

        start = time.monotonic()
        payloads, timed_out = loop.get_batch_requests(lit_api, q, transport)
        elapsed = time.monotonic() - start

        assert len(payloads) == 1
        assert elapsed < 0.001  # no adaptive wait
        assert timed_out == []

    # ==================================================================
    # 3. Medium load: partial batch + queue has depth → short wait
    # ==================================================================
    def test_medium_load_waits_when_queue_has_depth(self, loop, lit_api, transport):
        """Drain leaves partial batch, but qsize() > 0 → wait up to 2ms."""
        q = Queue()
        # Enqueue 2 quickly, then 2 more after a tiny delay
        self._enqueue(q, 2)

        def delayed_enqueue():
            time.sleep(0.0005)  # 0.5ms
            self._enqueue(q, 2)

        threading.Thread(target=delayed_enqueue, daemon=True).start()
        # Give the thread a moment to start
        time.sleep(0.0001)

        start = time.monotonic()
        payloads, timed_out = loop.get_batch_requests(lit_api, q, transport)
        elapsed = time.monotonic() - start

        # Should have collected all 4 (or at least > 2)
        assert len(payloads) >= 2
        # Waited some time (the adaptive window) but < 5ms
        assert elapsed < 0.005
        assert timed_out == []

    # ==================================================================
    # 4. Partial batch, queue empty → small wait (1ms cap)
    # ==================================================================
    def test_partial_batch_empty_queue_short_wait(self, loop, lit_api, transport):
        """2 requests, nothing else coming → wait at most 1ms."""
        q = Queue()
        self._enqueue(q, 2)

        start = time.monotonic()
        payloads, timed_out = loop.get_batch_requests(lit_api, q, transport)
        elapsed = time.monotonic() - start

        assert len(payloads) == 2
        # Should have waited a tiny bit (up to 1ms) but not the full base_timeout
        assert elapsed < 0.003
        assert timed_out == []

    # ==================================================================
    # 5. Sentinel handling
    # ==================================================================
    def test_sentinel_raises_stop_loop(self, loop, lit_api, transport):
        """A sentinel value in the queue should raise _StopLoopError."""
        q = Queue()
        q.put(_SENTINEL_VALUE)

        with pytest.raises(_StopLoopError):
            loop.get_batch_requests(lit_api, q, transport)

    def test_sentinel_during_drain_raises_stop_loop(self, loop, lit_api, transport):
        """Sentinel encountered during non-blocking drain must also stop."""
        q = Queue()
        q.put((0, "uid-0", time.monotonic(), {}))
        q.put(_SENTINEL_VALUE)

        with pytest.raises(_StopLoopError):
            loop.get_batch_requests(lit_api, q, transport)

    # ==================================================================
    # 6. Request timeout eviction
    # ==================================================================
    def test_expired_request_is_timed_out(self, loop, lit_api, transport):
        """Requests older than request_timeout should land in timed_out_uids."""
        q = Queue()
        lit_api.request_timeout = 0.05  # 50ms

        old_timestamp = time.monotonic() - 0.1  # 100ms ago
        q.put((0, "expired", old_timestamp, {}))
        q.put((0, "fresh", time.monotonic(), {}))

        payloads, timed_out = loop.get_batch_requests(lit_api, q, transport)

        assert (0, "expired") in timed_out
        assert len(payloads) == 1
        assert payloads[0][1] == "fresh"

    # ==================================================================
    # 7. Edge: max_batch_size == 1 behaves like single-loop
    # ==================================================================
    def test_batch_size_one_returns_single(self, loop, lit_api, transport):
        """With max_batch_size=1, only one request is ever returned."""
        q = Queue()
        lit_api.max_batch_size = 1
        self._enqueue(q, 5)

        payloads, _ = loop.get_batch_requests(lit_api, q, transport)
        assert len(payloads) == 1
