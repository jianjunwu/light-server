"""Tests for resource leak fixes (response_buffer, mp.Queue, GPU memory, etc.)."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry
from light_server.http.handlers import _do_litapi_infer
from light_server.http.state import HTTPState
from litserve.utils import ResponseBufferItem


class _MockQueue:
    """Picklable mock queue for manager.dict() compatibility."""

    def __init__(self):
        self._closed = False
        self._joined = False

    def close(self):
        self._closed = True

    def join_thread(self):
        self._joined = True

    def put(self, item):
        pass

    def get(self):
        return None


class TestResponseBufferCleanup:
    """Verify response_buffer entries are cleaned up on all exit paths."""

    @pytest.fixture
    def state(self):
        from light_server.config import Config
        from light_server.core.server import LightServer
        from pathlib import Path

        config = Config()
        config.grpc.enabled = False
        config.metrics.enabled = False
        config.model_repository.path = "/tmp/test_repo"
        config.server.timeout = 1.0
        server = LightServer(config)
        http_state = HTTPState(
            registry=server.registry,
            transport=server.transport,
            config=server.config,
            response_queue_id=0,
            repo_path=Path(server.config.model_repository.path),
            log_queue=server._log_queue,
            metrics_dir=server._metrics_dir,
            model_manager=server.model_manager,
        )
        http_state.init_worker_locals()
        http_state.registry.register("m", "1", {})
        http_state.registry.set_status("m", "1", "READY")
        return http_state

    def test_cancelled_error_cleans_response_buffer(self, state):
        """If the handler is cancelled (client disconnect), uid must be removed."""
        uid = "test-uid-cancel"

        async def _run():
            with patch("light_server.http.handlers.submit_infer", return_value=uid):
                with patch("asyncio.Event.wait", side_effect=asyncio.CancelledError):
                    await _do_litapi_infer(state, "m", "1", {"input": 1})

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(_run())

        assert uid not in state.response_buffer

    def test_timeout_error_cleans_response_buffer(self, state):
        """Timeout must pop the uid from response_buffer."""
        uid = "test-uid-timeout"

        async def _run():
            with patch("light_server.http.handlers.submit_infer", return_value=uid):
                with patch("asyncio.Event.wait", side_effect=asyncio.TimeoutError):
                    await _do_litapi_infer(state, "m", "1", {"input": 1})

        with pytest.raises(Exception):  # HTTPException
            asyncio.run(_run())

        assert uid not in state.response_buffer


class TestTeardownHook:
    """Verify teardown() hook is invoked on model unload."""

    def test_unload_calls_teardown(self, tmp_path: Path):
        """_unload_version must call lit_api.teardown()."""
        registry = ModelRegistry()
        manager = ModelManager(
            repo_path=tmp_path,
            registry=registry,
        )

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False

        registry.register("test_model", "1")

        mock_api = MagicMock()
        mock_api.teardown = MagicMock()

        manager._workers["test_model_1"] = [mock_worker]
        manager._litapi_instances["test_model_1"] = mock_api
        manager._workers_setup_status["test_model_1"] = mp.Manager().dict()

        result = manager.unload("test_model", "1")
        assert result is True
        mock_api.teardown.assert_called_once()

    def test_teardown_exception_does_not_crash_unload(self, tmp_path: Path):
        """If teardown raises, unload should still succeed."""
        registry = ModelRegistry()
        manager = ModelManager(
            repo_path=tmp_path,
            registry=registry,
        )

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False

        registry.register("test_model", "1")

        mock_api = MagicMock()
        mock_api.teardown = MagicMock(side_effect=RuntimeError("boom"))

        manager._workers["test_model_1"] = [mock_worker]
        manager._litapi_instances["test_model_1"] = mock_api
        manager._workers_setup_status["test_model_1"] = mp.Manager().dict()

        result = manager.unload("test_model", "1")
        assert result is True


class TestArtifactCacheCleanup:
    """Verify artifact cache is purged when no versions remain."""

    def test_unload_purges_artifact_cache_when_last_version(self, tmp_path: Path):
        """When the last version of an artifact model is unloaded, cache is purged."""
        registry = ModelRegistry()
        manager = ModelManager(
            repo_path=tmp_path,
            registry=registry,
        )

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False

        registry.register("test_model", "1")
        manager._artifact_model_paths["test_model"] = tmp_path / "cached" / "test_model"

        manager._workers["test_model_1"] = [mock_worker]
        manager._litapi_instances["test_model_1"] = MagicMock()
        manager._workers_setup_status["test_model_1"] = mp.Manager().dict()

        with patch("light_server.artifact.cache.ArtifactCache.purge") as mock_purge:
            result = manager.unload("test_model", "1")
            assert result is True
            mock_purge.assert_called_once_with("test_model")
            assert "test_model" not in manager._artifact_model_paths

    def test_unload_skips_purge_if_other_versions_loaded(self, tmp_path: Path):
        """If other versions are still loaded, artifact cache should not be purged."""
        registry = ModelRegistry()
        manager = ModelManager(
            repo_path=tmp_path,
            registry=registry,
        )

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False

        registry.register("test_model", "1")
        registry.register("test_model", "2")
        manager._artifact_model_paths["test_model"] = tmp_path / "cached" / "test_model"

        manager._workers["test_model_1"] = [mock_worker]
        manager._litapi_instances["test_model_1"] = MagicMock()
        manager._workers_setup_status["test_model_1"] = mp.Manager().dict()

        with patch("light_server.artifact.cache.ArtifactCache.purge") as mock_purge:
            result = manager.unload("test_model", "1")
            assert result is True
            mock_purge.assert_not_called()


class TestQueueCleanupOnUnload:
    """Verify request queues are closed on model unload."""

    def test_unload_closes_request_queue(self, tmp_path: Path):
        """_unload_version must call close() and join_thread() on the queue."""
        registry = ModelRegistry()
        manager = ModelManager(
            repo_path=tmp_path,
            registry=registry,
        )

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False

        registry.register("test_model", "1")

        manager._workers["test_model_1"] = [mock_worker]
        manager._litapi_instances["test_model_1"] = MagicMock()
        manager._workers_setup_status["test_model_1"] = mp.Manager().dict()

        # Monkeypatch get_queue to return a mock with close/join_thread
        mock_queue = MagicMock()
        registry.get_queue = lambda name, version=None: mock_queue

        result = manager.unload("test_model", "1")
        assert result is True

        mock_queue.close.assert_called_once()
        mock_queue.join_thread.assert_called_once()
        mock_worker.terminate.assert_called_once()

    def test_unload_cleans_workers_setup_status(self, tmp_path: Path):
        """Per-worker keys in the manager.dict() must be removed on unload."""
        registry = ModelRegistry()
        manager = ModelManager(
            repo_path=tmp_path,
            registry=registry,
        )

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False

        registry.register("test_model", "1")

        manager._workers["test_model_1"] = [mock_worker]
        manager._litapi_instances["test_model_1"] = MagicMock()

        # Simulate manager.dict() with per-worker sub-keys
        setup_dict = mp.Manager().dict()
        setup_dict["test_model_1_0"] = "ready"
        setup_dict["test_model_1_1"] = "ready"
        manager._workers_setup_status["test_model_1"] = setup_dict

        result = manager.unload("test_model", "1")
        assert result is True

        # All per-worker keys should be gone
        assert "test_model_1_0" not in setup_dict
        assert "test_model_1_1" not in setup_dict

    def test_unload_without_queue_does_not_crash(self, tmp_path: Path):
        """If queue is None (edge case), unload should not raise."""
        registry = ModelRegistry()
        manager = ModelManager(
            repo_path=tmp_path,
            registry=registry,
        )

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False

        registry.register("test_model", "1")
        # No queue set

        manager._workers["test_model_1"] = [mock_worker]
        manager._litapi_instances["test_model_1"] = MagicMock()
        manager._workers_setup_status["test_model_1"] = mp.Manager().dict()

        result = manager.unload("test_model", "1")
        assert result is True
