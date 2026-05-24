"""TTL-based response buffer with automatic expiry and size limits."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_SENTINEL = object()


class TTLResponseBuffer:
    """Thread-safe response buffer that auto-expires stale entries.

    Mimics a subset of ``dict`` operations so existing code can use
    ``buffer[uid] = item``, ``buffer.pop(uid)``, and ``buffer.get(uid)``
    without changes.
    """

    def __init__(
        self,
        ttl_seconds: float = 60.0,
        max_size: int = 100_000,
        cleanup_interval_seconds: float = 30.0,
    ):
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._cleanup_interval = cleanup_interval_seconds
        self._buffer: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._cleanup_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the background cleanup thread."""
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            return
        self._stop_event.clear()
        t = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="response-buffer-cleanup",
        )
        t.start()
        self._cleanup_thread = t

    def stop(self) -> None:
        """Signal the cleanup thread to stop."""
        self._stop_event.set()
        if self._cleanup_thread is not None:
            self._cleanup_thread.join(timeout=2)

    def _cleanup_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._cleanup_interval)
            if self._stop_event.is_set():
                break
            self._expire_stale()

    def _expire_stale(self) -> None:
        now = time.monotonic()
        cutoff = now - self._ttl
        with self._lock:
            stale = [
                uid for uid, (_, inserted_at) in self._buffer.items()
                if inserted_at < cutoff
            ]
            for uid in stale:
                del self._buffer[uid]
            if stale:
                logger.warning(
                    f"Expired {len(stale)} stale response buffer entries"
                )
            # Hard size limit — evict oldest
            excess = len(self._buffer) - self._max_size
            if excess > 0:
                sorted_items = sorted(
                    self._buffer.items(), key=lambda x: x[1][1]
                )
                for uid, _ in sorted_items[:excess]:
                    del self._buffer[uid]
                logger.warning(
                    f"Response buffer exceeded max_size ({self._max_size}), "
                    f"removed {excess} oldest entries"
                )

    # ------------------------------------------------------------------
    # Dict-like interface
    # ------------------------------------------------------------------
    def __setitem__(self, uid: str, item: Any) -> None:
        with self._lock:
            self._buffer[uid] = (item, time.monotonic())
            # If already at limit, evict the oldest entry immediately
            if len(self._buffer) > self._max_size:
                oldest_uid = min(self._buffer, key=lambda k: self._buffer[k][1])
                del self._buffer[oldest_uid]
                logger.warning(
                    "Response buffer at max_size, evicted oldest entry"
                )

    def __getitem__(self, uid: str) -> Any:
        with self._lock:
            return self._buffer[uid][0]

    def get(self, uid: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._buffer.get(uid, _SENTINEL)
            if entry is _SENTINEL:
                return default
            return entry[0]

    def pop(self, uid: str, default: Any = _SENTINEL) -> Any:
        with self._lock:
            entry = self._buffer.pop(uid, _SENTINEL)
            if entry is _SENTINEL:
                if default is _SENTINEL:
                    raise KeyError(uid)
                return default
            return entry[0]

    def __contains__(self, uid: str) -> bool:
        with self._lock:
            return uid in self._buffer

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)
