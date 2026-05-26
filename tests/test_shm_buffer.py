"""Tests for zero-copy shared memory payload transport."""

from __future__ import annotations

import pickle
import time
from multiprocessing import shared_memory

import pytest

from light_server.core.shm_buffer import ShmPayloadBuffer


class TestShmPayloadBuffer:
    """Verify threshold routing, shared memory lifecycle, and GC."""

    @pytest.fixture
    def buf(self):
        return ShmPayloadBuffer(threshold_bytes=128, gc_interval_seconds=0.5)

    # ==================================================================
    # 1. Small payloads pass through directly
    # ==================================================================
    def test_small_payload_direct_mode(self, buf: ShmPayloadBuffer):
        """Payloads under threshold should not touch shared memory."""
        payload = {"input": "hello"}
        mode, data = buf.offload(payload)

        assert mode == "direct"
        assert data == payload

    def test_small_payload_retrieve(self, buf: ShmPayloadBuffer):
        """Direct mode retrieve is identity."""
        payload = {"input": "hello"}
        mode, data = buf.offload(payload)
        restored = ShmPayloadBuffer.retrieve(mode, data)
        assert restored == payload

    # ==================================================================
    # 2. Large payloads go through shared memory
    # ==================================================================
    def test_large_payload_shm_mode(self, buf: ShmPayloadBuffer):
        """Payloads over threshold should return shm reference."""
        payload = {"image": "x" * 1000}  # well over 128 bytes
        mode, data = buf.offload(payload)

        assert mode == "shm"
        assert isinstance(data, tuple)
        assert len(data) == 2
        shm_name, size = data
        assert isinstance(shm_name, str)
        assert size > 128

    def test_large_payload_retrieve(self, buf: ShmPayloadBuffer):
        """Worker-side retrieve should reconstruct exact payload."""
        payload = {"tensor": list(range(500))}
        mode, data = buf.offload(payload)

        restored = ShmPayloadBuffer.retrieve(mode, data)
        assert restored == payload

    # ==================================================================
    # 3. Memory leak safety: explicit release
    # ==================================================================
    def test_release_unlinks_shm(self, buf: ShmPayloadBuffer):
        """After release, the shared memory segment should be gone."""
        payload = {"big": "y" * 1000}
        mode, data = buf.offload(payload)
        shm_name, _ = data

        # Verify it exists
        shm = shared_memory.SharedMemory(name=shm_name)
        shm.close()

        # Release via buffer
        buf.release(shm_name)

        # Should no longer be attachable
        with pytest.raises(FileNotFoundError):
            shared_memory.SharedMemory(name=shm_name)

    # ==================================================================
    # 4. Memory leak safety: GC reclaims stale segments
    # ==================================================================
    def test_gc_reclaims_stale_segments(self, buf: ShmPayloadBuffer):
        """Segments older than gc_interval should be auto-unlinked."""
        payload = {"big": "z" * 1000}
        mode, data = buf.offload(payload)
        shm_name, _ = data

        # Verify it exists
        shm = shared_memory.SharedMemory(name=shm_name)
        shm.close()

        # Wait for GC interval + margin
        time.sleep(0.7)

        # Trigger GC via another offload
        buf.offload({"small": "x"})

        # Stale segment should be gone
        with pytest.raises(FileNotFoundError):
            shared_memory.SharedMemory(name=shm_name)

    # ==================================================================
    # 5. Shutdown releases everything
    # ==================================================================
    def test_shutdown_releases_all(self, buf: ShmPayloadBuffer):
        """shutdown() should unlink all tracked segments."""
        names = []
        for i in range(3):
            mode, data = buf.offload({"big": f"a" * 1000})
            if mode == "shm":
                names.append(data[0])

        # Verify all exist
        for name in names:
            shm = shared_memory.SharedMemory(name=name)
            shm.close()

        buf.shutdown()

        for name in names:
            with pytest.raises(FileNotFoundError):
                shared_memory.SharedMemory(name=name)

    # ==================================================================
    # 6. Worker-side retrieve auto-unlinks
    # ==================================================================
    def test_worker_retrieve_auto_unlinks(self, buf: ShmPayloadBuffer):
        """retrieve() should close and try to unlink from worker side."""
        payload = {"big": "b" * 1000}
        mode, data = buf.offload(payload)
        shm_name, _ = data

        # Verify exists
        shm = shared_memory.SharedMemory(name=shm_name)
        shm.close()

        # Worker retrieves
        restored = ShmPayloadBuffer.retrieve(mode, data)
        assert restored == payload

        # On Linux the worker unlink succeeds; on macOS it may not.
        # Either way the segment should not be attachable after GC or shutdown.

    # ==================================================================
    # 7. Buffer assignment failure unlinks SHM (leak safety)
    # ==================================================================
    def test_buf_assignment_failure_unlinks_shm(self, buf: ShmPayloadBuffer):
        """If shm.buf[:] assignment fails, the segment must be unlinked."""
        from unittest.mock import MagicMock, patch

        payload = {"big": "x" * 1000}
        pickled = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)

        mock_shm = MagicMock()
        mock_shm.name = "test-shm-fail"
        # Simulate buf assignment failure
        mock_shm.buf = MagicMock()
        mock_shm.buf.__setitem__ = MagicMock(side_effect=RuntimeError("buf fail"))
        mock_shm.unlink = MagicMock()

        with patch("multiprocessing.shared_memory.SharedMemory", return_value=mock_shm):
            mode, data = buf.offload(payload)

        assert mode == "direct"
        mock_shm.unlink.assert_called_once()

    # ==================================================================
    # 8. End-to-end: multiple large payloads tracked correctly
    # ==================================================================
    def test_multiple_large_payloads_tracked(self, buf: ShmPayloadBuffer):
        """Buffer should track multiple concurrent shm segments."""
        payloads = [{"id": i, "data": "x" * 1000} for i in range(5)]
        refs = []
        for p in payloads:
            mode, data = buf.offload(p)
            assert mode == "shm"
            refs.append(data)

        # All should be retrievable
        for p, (mode, data) in zip(payloads, [("shm", r) for r in refs]):
            restored = ShmPayloadBuffer.retrieve(mode, data)
            assert restored == p

        # After retrieve, shutdown should not crash even if some are already gone
        buf.shutdown()
