"""Shared memory payload buffer for zero-copy IPC of large requests."""

from __future__ import annotations

import pickle
import threading
import time
from multiprocessing import shared_memory
from typing import Any


class ShmPayloadBuffer:
    """Offloads large payloads to shared memory to avoid pickle overhead.

    Small payloads (< threshold) pass through directly.
    Large payloads are pickled into a SharedMemory segment; only a reference
    (shm_name, size) is sent through the queue.

    Thread-safe.  Gracefully falls back to direct mode when SharedMemory
    is unavailable (e.g. macOS limits, name collisions).
    """

    def __init__(self, threshold_bytes: int = 4096, gc_interval_seconds: float = 30.0):
        self.threshold = threshold_bytes
        self._gc_interval = gc_interval_seconds
        self._lock = threading.Lock()
        self._created_at: dict[str, float] = {}  # shm_name -> creation time
        self._last_gc = time.monotonic()

    # ------------------------------------------------------------------
    #  Internals
    # ------------------------------------------------------------------
    def _maybe_gc(self) -> None:
        """Unlink stale shared memory segments (safety net for worker crashes)."""
        now = time.monotonic()
        if now - self._last_gc < self._gc_interval:
            return
        self._last_gc = now
        cutoff = now - self._gc_interval
        with self._lock:
            stale = [name for name, t in self._created_at.items() if t < cutoff]
            for name in stale:
                self._created_at.pop(name, None)
                try:
                    shm = shared_memory.SharedMemory(name=name)
                    shm.close()
                    shm.unlink()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    #  Producer side (HTTP handler / ModelManager)
    # ------------------------------------------------------------------
    def offload(self, payload: Any) -> tuple[str, Any]:
        """Return (mode, data) suitable for queue transmission.

        mode is either ``"direct"`` (pass through) or ``"shm"``
        (reference to a shared memory segment).
        """
        self._maybe_gc()

        pickled = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
        if len(pickled) <= self.threshold:
            return "direct", payload

        try:
            shm = shared_memory.SharedMemory(create=True, size=len(pickled))
            shm.buf[: len(pickled)] = pickled
            with self._lock:
                self._created_at[shm.name] = time.monotonic()
            return "shm", (shm.name, len(pickled))
        except Exception:
            # Fallback: SharedMemory may fail on some platforms / limits
            return "direct", payload

    # ------------------------------------------------------------------
    #  Consumer side (worker process)
    # ------------------------------------------------------------------
    @staticmethod
    def retrieve(mode: str, data: Any) -> Any:
        """Reconstruct payload from direct or shared-memory representation.

        Must be called **inside the worker process**.
        """
        if mode == "direct":
            return data

        shm_name, size = data
        shm = None
        try:
            shm = shared_memory.SharedMemory(name=shm_name)
            payload = pickle.loads(shm.buf[:size])
            return payload
        except Exception as exc:
            raise RuntimeError(
                f"Failed to retrieve payload from shared memory {shm_name}"
            ) from exc
        finally:
            if shm is not None:
                shm.close()
                # Try to unlink from worker side; on macOS this may fail,
                # in which case the GC path on the manager side cleans it up.
                try:
                    shm.unlink()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    #  Cleanup
    # ------------------------------------------------------------------
    def release(self, shm_name: str) -> None:
        """Explicitly release a shared memory segment."""
        with self._lock:
            self._created_at.pop(shm_name, None)
        try:
            shm = shared_memory.SharedMemory(name=shm_name)
            shm.close()
            shm.unlink()
        except Exception:
            pass

    def shutdown(self) -> None:
        """Unlink all remaining shared memory segments."""
        with self._lock:
            names = list(self._created_at.keys())
            self._created_at.clear()
        for name in names:
            try:
                shm = shared_memory.SharedMemory(name=name)
                shm.close()
                shm.unlink()
            except Exception:
                pass
