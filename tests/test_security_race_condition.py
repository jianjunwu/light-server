"""Tests for race-condition prevention in model load/unload."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry


class TestRaceCondition:
    def test_concurrent_load_deduplication(self, tmp_path):
        """Multiple threads loading the same model must not create duplicate workers."""
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)

        # Prepare a fake model directory with minimal config.yaml
        model_dir = tmp_path / "test_model" / "1"
        model_dir.mkdir(parents=True)
        (model_dir / "config.yaml").write_text("max_batch_size: 1\n")
        (model_dir / "model.py").write_text(
            "from litserve import LitAPI\n"
            "class MyModel(LitAPI):\n"
            "    def setup(self, device): pass\n"
            "    def decode_request(self, request): return request\n"
            "    def predict(self, x): return x\n"
            "    def encode_response(self, output): return output\n"
        )

        call_count = [0]
        lock = threading.Lock()

        def slow_launch(*args, **kwargs):
            with lock:
                call_count[0] += 1
            time.sleep(0.2)  # Simulate slow worker startup
            mock_proc = MagicMock()
            mock_proc.is_alive.return_value = True
            return [mock_proc]

        results = []
        errors = []

        def loader():
            try:
                success = mgr.load("test_model", "1")
                results.append(success)
            except Exception as e:
                errors.append(e)

        with patch.object(mgr, "_launch_workers", side_effect=slow_launch):
            with patch.object(mgr, "_wait_for_ready"):
                threads = [threading.Thread(target=loader) for _ in range(5)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=5)

        assert not errors, f"Errors during concurrent load: {errors}"
        # _launch_workers should only have been called once
        assert call_count[0] == 1, f"_launch_workers called {call_count[0]} times"
        key = mgr._worker_key("test_model", "1")
        assert key in mgr._workers
        assert len(mgr._workers[key]) == 1

    def test_load_unload_alternating_consistency(self, tmp_path):
        """Rapid load/unload cycles must leave internal state consistent."""
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)

        model_dir = tmp_path / "test_model" / "1"
        model_dir.mkdir(parents=True)
        (model_dir / "config.yaml").write_text("max_batch_size: 1\n")
        (model_dir / "model.py").write_text(
            "from litserve import LitAPI\n"
            "class MyModel(LitAPI):\n"
            "    def setup(self, device): pass\n"
            "    def decode_request(self, request): return request\n"
            "    def predict(self, x): return x\n"
            "    def encode_response(self, output): return output\n"
        )

        mock_proc = MagicMock()
        mock_proc.is_alive.return_value = True

        def fast_launch(*args, **kwargs):
            return [mock_proc]

        errors = []

        def load_unload_loop():
            for _ in range(10):
                try:
                    mgr.load("test_model", "1")
                    time.sleep(0.01)
                    mgr.unload("test_model", "1")
                    time.sleep(0.01)
                except Exception as e:
                    errors.append(e)

        with patch.object(mgr, "_launch_workers", side_effect=fast_launch):
            with patch.object(mgr, "_wait_for_ready"):
                t1 = threading.Thread(target=load_unload_loop)
                t2 = threading.Thread(target=load_unload_loop)
                t1.start()
                t2.start()
                t1.join(timeout=10)
                t2.join(timeout=10)

        assert not errors, f"Errors during alternating load/unload: {errors}"
        # After all operations, state should be clean
        key = mgr._worker_key("test_model", "1")
        assert key not in mgr._workers
        assert not registry.list_versions("test_model")

    def test_infer_during_unload_no_crash(self, tmp_path):
        """Infer submitted while unload is in progress should not crash."""
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)

        # Set up a fake ready model
        registry.register("test_model", "1", {"max_queue_size": 10}, model_type="litapi")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        q = mgr._manager.Queue(maxsize=10)
        registry.set_worker_queues("test_model", "1", [q])
        mgr._workers["test_model_1"] = [MagicMock()]

        errors = []

        def infer_loop():
            for _ in range(10):
                try:
                    mgr.infer("test_model", {"x": 1})
                except Exception as e:
                    # QueueFullError or RuntimeError are acceptable during unload
                    from light_server.core.exceptions import QueueFullError
                    if isinstance(e, QueueFullError):
                        continue
                    if "not ready" in str(e).lower():
                        continue
                    errors.append(e)

        def unload_loop():
            for _ in range(3):
                time.sleep(0.01)
                try:
                    mgr.unload("test_model", "1")
                except Exception as e:
                    errors.append(e)

        t_infer = threading.Thread(target=infer_loop)
        t_unload = threading.Thread(target=unload_loop)
        t_infer.start()
        t_unload.start()
        t_infer.join(timeout=10)
        t_unload.join(timeout=10)

        # Should not see unhandled crashes
        assert not errors, f"Unexpected errors: {errors}"
