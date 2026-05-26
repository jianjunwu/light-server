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


class FakeQueue:
    """Picklable fake queue for testing."""

    def __init__(self, maxsize: int = 0) -> None:
        self._items: list[Any] = []
        self._maxsize = maxsize

    def put_nowait(self, item: Any) -> None:
        if self._maxsize and len(self._items) >= self._maxsize:
            raise Exception("Queue full")
        self._items.append(item)

    def put(self, item: Any, timeout: float | None = None) -> None:
        self.put_nowait(item)

    def get(self) -> Any:
        return self._items.pop(0)

    def qsize(self) -> int:
        return len(self._items)


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


class TestGrpcPredictResponseBufferCleanup:
    """Verify gRPC Predict cleans response_buffer on all exit paths."""

    @pytest.fixture
    def mock_server(self):
        from light_server.config import Config
        from light_server.core.response_buffer import TTLResponseBuffer

        server = MagicMock()
        server.registry = MagicMock()
        server.registry.is_ready.return_value = True
        server.model_manager = MagicMock()
        server.model_manager.infer.return_value = "grpc-uid-123"
        server.response_buffer = TTLResponseBuffer()
        server.config = Config()
        server.config.server.timeout = 1.0
        return server

    def test_json_decode_error_cleans_buffer(self, mock_server):
        """Invalid JSON must not leave uid in response_buffer."""
        from light_server.grpc.servicer import InferenceServicer
        from light_server.grpc.proto import litserve_pb2

        servicer = InferenceServicer(mock_server)
        request = litserve_pb2.PredictRequest(
            model_name="m", version="1", payload=b"not-json"
        )
        context = MagicMock()

        servicer.Predict(request, context)
        assert "grpc-uid-123" not in mock_server.response_buffer

    def test_infer_exception_cleans_buffer(self, mock_server):
        """If infer() raises, uid must not remain in response_buffer."""
        from light_server.grpc.servicer import InferenceServicer
        from light_server.grpc.proto import litserve_pb2
        from light_server.core.exceptions import ModelNotReadyError

        mock_server.model_manager.infer.side_effect = ModelNotReadyError("boom")
        servicer = InferenceServicer(mock_server)
        request = litserve_pb2.PredictRequest(
            model_name="m", version="1", payload=b'{"input": 1}'
        )
        context = MagicMock()

        servicer.Predict(request, context)
        assert "grpc-uid-123" not in mock_server.response_buffer

    def test_timeout_cleans_buffer(self, mock_server):
        """Timeout path already cleans buffer; verify with test."""
        from light_server.grpc.servicer import InferenceServicer
        from light_server.grpc.proto import litserve_pb2

        servicer = InferenceServicer(mock_server)
        request = litserve_pb2.PredictRequest(
            model_name="m", version="1", payload=b'{"input": 1}'
        )
        context = MagicMock()

        servicer.Predict(request, context)
        # event.wait returns False by default (timeout), so uid is popped
        assert "grpc-uid-123" not in mock_server.response_buffer


class TestAdminQueueCleanup:
    """Verify admin IPC queues are closed on shutdown."""

    def test_admin_response_queues_saved_on_multi_http(self):
        """_start_http_multi must save admin_response_queues as instance attr."""
        from light_server.config import Config
        from light_server.core.server import LightServer

        config = Config()
        config.server.http_workers = 2
        config.server.http_port = 0
        server = LightServer(config)

        mock_queues = [MagicMock(), MagicMock()]
        server._manager.Queue = MagicMock(side_effect=mock_queues + [MagicMock()])

        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock_cls.return_value = mock_sock
            with patch.object(server._mp_ctx, "Process") as mock_proc:
                mock_proc.return_value.is_alive.return_value = False
                server._shutdown_event.set()
                server._start_http_multi(2)

        assert hasattr(server, "_admin_response_queues")
        assert len(server._admin_response_queues) == 2

    def test_shutdown_closes_admin_queues(self):
        """shutdown() must close admin_queue and admin_response_queues."""
        from light_server.config import Config
        from light_server.core.server import LightServer

        config = Config()
        server = LightServer(config)

        admin_queue = MagicMock()
        resp_queues = [MagicMock(), MagicMock()]
        server._admin_queue = admin_queue
        server._admin_response_queues = resp_queues

        # Minimal mocks for shutdown to run without side effects
        server.response_buffer = MagicMock()
        server._http_worker_procs = []
        server.registry.list_loaded = MagicMock(return_value=[])
        server.transport = MagicMock()
        server.transport._queues = []
        server.model_manager._workers = {}
        server.model_manager.shutdown = MagicMock()
        server._grpc_server = None
        server._metrics_server = None
        server._log_consumer = None
        server._metrics_dir = None

        server.shutdown()

        admin_queue.close.assert_called_once()
        admin_queue.join_thread.assert_called_once()
        for q in resp_queues:
            q.close.assert_called_once()
            q.join_thread.assert_called_once()


class TestLogQueueCleanup:
    """Verify log queue is closed on server shutdown."""

    def test_shutdown_closes_log_queue(self):
        """shutdown() must close and join_thread the log queue."""
        from light_server.config import Config
        from light_server.core.server import LightServer

        config = Config()
        server = LightServer(config)

        log_queue = MagicMock()
        log_consumer = MagicMock()
        server._log_queue = log_queue
        server._log_consumer = log_consumer

        # Minimal mocks for shutdown to run without side effects
        server.response_buffer = MagicMock()
        server._http_worker_procs = []
        server.registry.list_loaded = MagicMock(return_value=[])
        server.transport = MagicMock()
        server.transport._queues = []
        server.model_manager._workers = {}
        server.model_manager.shutdown = MagicMock()
        server._grpc_server = None
        server._metrics_server = None
        server._metrics_dir = None
        server._admin_queue = None
        server._admin_response_queues = []

        server.shutdown()

        log_consumer.stop.assert_called_once()
        log_queue.close.assert_called_once()
        log_queue.join_thread.assert_called_once()


class TestMetricsDirCleanup:
    """Verify Prometheus metrics directory cleanup respects user-provided dirs."""

    def test_shutdown_rmtrees_temp_metrics_dir(self, tmp_path: Path):
        """If we created the temp dir, shutdown must remove it."""
        from light_server.config import Config
        from light_server.core.server import LightServer

        config = Config()
        server = LightServer(config)

        metrics_dir = tmp_path / "prom_metrics"
        metrics_dir.mkdir()
        server._metrics_dir = str(metrics_dir)
        server._metrics_dir_created = True

        # Minimal mocks for shutdown to run without side effects
        server.response_buffer = MagicMock()
        server._http_worker_procs = []
        server.registry.list_loaded = MagicMock(return_value=[])
        server.transport = MagicMock()
        server.transport._queues = []
        server.model_manager._workers = {}
        server.model_manager.shutdown = MagicMock()
        server._grpc_server = None
        server._metrics_server = None
        server._log_queue = None
        server._log_consumer = None
        server._admin_queue = None
        server._admin_response_queues = []

        server.shutdown()

        assert not metrics_dir.exists()

    def test_shutdown_does_not_rmtree_user_metrics_dir(self, tmp_path: Path):
        """If the user provided the dir via env var, shutdown must not remove it."""
        from light_server.config import Config
        from light_server.core.server import LightServer

        config = Config()
        server = LightServer(config)

        metrics_dir = tmp_path / "user_metrics"
        metrics_dir.mkdir()
        # Create a dummy file to prove the dir is not deleted
        (metrics_dir / "important.txt").write_text("keep me")

        server._metrics_dir = str(metrics_dir)
        server._metrics_dir_created = False

        # Minimal mocks for shutdown to run without side effects
        server.response_buffer = MagicMock()
        server._http_worker_procs = []
        server.registry.list_loaded = MagicMock(return_value=[])
        server.transport = MagicMock()
        server.transport._queues = []
        server.model_manager._workers = {}
        server.model_manager.shutdown = MagicMock()
        server._grpc_server = None
        server._metrics_server = None
        server._log_queue = None
        server._log_consumer = None
        server._admin_queue = None
        server._admin_response_queues = []

        server.shutdown()

        assert metrics_dir.exists()
        assert (metrics_dir / "important.txt").read_text() == "keep me"


class TestHookCacheCleanup:
    """Verify HTTPState hook cache is cleared when model is unloaded."""

    def test_hook_cache_cleared_when_model_unloaded(self, isolated_model_repo):
        """get_litapi_hooks() must invalidate cache after model unload."""
        from light_server.config import Config
        from light_server.http.state import HTTPState
        from light_server.core.registry import ModelRegistry

        registry = ModelRegistry()
        model_dir = str(isolated_model_repo / "test_model" / "1")
        registry.register("test_model", "1", model_dir=model_dir)
        registry.set_status("test_model", "1", "READY")

        config = Config()
        state = HTTPState(registry=registry, transport=MagicMock(), config=config)
        state.init_worker_locals()

        # Mock load_litapi_from_file to return a class with a hook
        mock_instance = MagicMock()
        mock_instance.on_request = MagicMock()
        with patch("light_server.core.loader.load_litapi_from_file") as mock_loader:
            mock_loader.return_value = lambda **kwargs: mock_instance
            hooks = state.get_litapi_hooks("test_model", "1")

        assert hooks is not None
        assert "test_model_1" in state._hook_cache

        # Simulate unload
        registry.remove("test_model", "1")

        # Next call should clear cache and return None
        hooks = state.get_litapi_hooks("test_model", "1")
        assert hooks is None
        assert "test_model_1" not in state._hook_cache


class TestEnsembleCancelledErrorCleanup:
    """Verify ensemble step cleans response_buffer on CancelledError."""

    def test_cancelled_error_cleans_response_buffer(self):
        """If event.wait() is cancelled, uid must be removed from buffer."""
        from light_server.config import Config
        from light_server.http.state import HTTPState
        from light_server.core.registry import ModelRegistry
        from light_server.core.ensemble import EnsembleExecutor, EnsembleStep
        from litserve.utils import ResponseBufferItem

        registry = ModelRegistry()
        registry.register("sub_model", "1")
        registry.set_status("sub_model", "1", "READY")
        registry.set_queue("sub_model", "1", FakeQueue())

        config = Config()
        config.server.timeout = 1.0
        state = HTTPState(registry=registry, transport=MagicMock(), config=config)
        state.init_worker_locals()

        executor = EnsembleExecutor()
        step = EnsembleStep(name="step1", model="sub_model", version="1", inputs={"input": "$request.value"})

        uid = "ensemble-uid-123"
        with patch("light_server.core.model_manager.submit_infer", return_value=uid):
            with patch("asyncio.Event.wait", side_effect=asyncio.CancelledError):
                coro = executor._execute_step(state, step, {"request": {"value": 42}}, "test_ensemble")
                with pytest.raises(asyncio.CancelledError):
                    asyncio.run(coro)

        assert uid not in state.response_buffer


class TestStreamSessionCleanup:
    """Verify StreamSession threads are cleaned up on worker exit."""

    def test_sentinel_cancels_stream_sessions(self):
        """run_bidirectional_loop must cancel and join all sessions on _SENTINEL_VALUE."""
        from queue import Queue
        from litserve.loops.base import _SENTINEL_VALUE
        from light_server.core.loops import BidirectionalStreamingLoop, StreamSession

        loop = BidirectionalStreamingLoop()
        mock_lit_api = MagicMock()
        mock_transport = MagicMock()
        mock_callback = MagicMock()

        session = StreamSession("test-stream", mock_lit_api, mock_transport, 0, loop)

        def fake_run():
            import time
            while not session.closed:
                time.sleep(0.01)

        session._run = fake_run
        loop.sessions["test-stream"] = session
        session.start()

        # Wait for thread to start
        import time
        time.sleep(0.05)
        assert session.thread is not None
        assert session.thread.is_alive()

        q = Queue()
        q.put(_SENTINEL_VALUE)
        loop.run_bidirectional_loop(mock_lit_api, q, mock_transport, mock_callback)

        assert not session.thread.is_alive()
        assert "test-stream" not in loop.sessions


class TestFileWatcherShutdown:
    """Verify file-watcher thread exits gracefully on stop_event."""

    def test_stop_event_stops_file_watcher(self):
        """_start_file_watcher must exit when stop_event is set."""
        from light_server.core.model_manager import _start_file_watcher
        from unittest.mock import MagicMock
        import threading
        import time

        lit_api = MagicMock()
        lit_api.logger = MagicMock()

        stop_event = threading.Event()
        _start_file_watcher(
            lit_api,
            Path("/tmp"),
            {"hot_reload_interval": 0.01, "hot_reload_patterns": ["*.py"]},
            stop_event,
        )

        # Wait for watcher to start
        time.sleep(0.05)
        watcher_thread = None
        for t in threading.enumerate():
            if t.name == "file-watcher":
                watcher_thread = t
                break

        assert watcher_thread is not None
        assert watcher_thread.is_alive()

        stop_event.set()
        watcher_thread.join(timeout=1)
        assert not watcher_thread.is_alive()


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


class TestHttpWorkerShmCleanup:
    """Verify HTTP worker shuts down its SHM buffer on exit."""

    def test_http_worker_shuts_down_shm_buffer(self):
        """http_worker_main must call shm_buffer.shutdown() on exit."""
        from light_server.http.worker import http_worker_main
        from light_server.config import Config

        config = Config()
        registry = ModelRegistry()
        state = HTTPState(registry=registry, transport=MagicMock(), config=config)

        mock_shm = MagicMock()
        mock_shm.shutdown = MagicMock()
        state._shm_buffer = mock_shm

        mock_sock = MagicMock()
        mock_sock.fileno.return_value = 99

        with patch("light_server.http.worker.uvicorn.Server") as mock_server_cls:
            mock_server_cls.return_value.run = MagicMock()
            with patch.object(state, "init_worker_locals"):
                http_worker_main(state, mock_sock)

        mock_shm.shutdown.assert_called_once()
