"""Tests for bounded request queue / DoS prevention."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from unittest.mock import MagicMock

import pytest

from light_server.core.exceptions import QueueFullError
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry


class TestQueueFullError:
    def test_infer_raises_when_queue_full(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)

        # Manually set up a ready model with a tiny queue
        registry.register("test_model", "1", {"max_queue_size": 2}, model_type="litapi")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        tiny_queue = mp.Manager().Queue(maxsize=2)
        registry.set_worker_queues("test_model", "1", [tiny_queue])

        # Fill the queue
        tiny_queue.put_nowait((0, "uid-1", 0.0, {"x": 1}))
        tiny_queue.put_nowait((0, "uid-2", 0.0, {"x": 2}))

        # Third request should raise QueueFullError
        with pytest.raises(QueueFullError):
            mgr.infer("test_model", {"x": 3})

    def test_infer_ok_when_queue_has_room(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)

        registry.register("test_model", "1", {"max_queue_size": 10}, model_type="litapi")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        q = mp.Manager().Queue(maxsize=10)
        registry.set_worker_queues("test_model", "1", [q])

        uid = mgr.infer("test_model", {"x": 1})
        assert uid is not None
        # qsize() is not supported on macOS, so just verify uid was generated

    def test_stream_open_raises_when_queue_full(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)

        registry.register("test_model", "1", {"max_queue_size": 1}, model_type="litapi")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        tiny_queue = mp.Manager().Queue(maxsize=1)
        registry.set_worker_queues("test_model", "1", [tiny_queue])

        tiny_queue.put_nowait((0, "uid-1", 0.0, {"x": 1}))

        with pytest.raises(QueueFullError):
            mgr.infer_stream_open("test_model", "stream-1")

        # Routing should have been rolled back
        assert "stream-1" not in mgr._stream_routing

    def test_stream_chunk_raises_when_queue_full(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)

        registry.register("test_model", "1", {"max_queue_size": 1}, model_type="litapi")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        tiny_queue = mp.Manager().Queue(maxsize=1)
        registry.set_worker_queues("test_model", "1", [tiny_queue])

        # Pre-register stream routing so chunk can be sent
        mgr._stream_routing["stream-1"] = 0
        tiny_queue.put_nowait((0, "uid-1", 0.0, {"x": 1}))

        with pytest.raises(QueueFullError):
            mgr.infer_stream_chunk("test_model", "stream-1", {"data": "chunk"})


class TestHTTPQueueLimit:
    def test_infer_handler_returns_429_on_queue_full(self):
        from light_server.http.handlers import _do_litapi_infer
        from light_server.http.state import HTTPState
        from light_server.core.server import LightServer
        from light_server.config import Config
        from light_server.core.exceptions import QueueFullError
        from light_server.core.model_manager import submit_infer

        config = Config()
        config.grpc.enabled = False
        config.metrics.enabled = False
        server = LightServer(config)

        state = HTTPState(
            registry=server.registry,
            transport=server.transport,
            config=server.config,
            response_queue_id=0,
            repo_path=server.config.model_repository.path,
            log_queue=server._log_queue,
            metrics_dir=server._metrics_dir,
            model_manager=server.model_manager,
        )
        state.init_worker_locals()

        # Patch submit_infer to always raise QueueFullError
        _orig_submit_infer = submit_infer
        import light_server.http.handlers as _handlers_mod

        def _mock_submit_infer(*args, **kwargs):
            raise QueueFullError("Queue full")

        _handlers_mod.submit_infer = _mock_submit_infer

        with pytest.raises(QueueFullError) as exc_info:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    _do_litapi_infer(state, "my_model", None, {"x": 1})
                )
            finally:
                loop.close()
        _handlers_mod.submit_infer = _orig_submit_infer
        assert exc_info.value.status_code == 429
        assert "full" in str(exc_info.value).lower()

    def test_ws_stream_handler_closes_on_queue_full(self):
        from light_server.http.handlers import _do_ws_stream
        from light_server.http.state import HTTPState
        from light_server.core.server import LightServer
        from light_server.config import Config
        from light_server.core.exceptions import QueueFullError
        from light_server.core.model_manager import submit_stream_open
        from fastapi import WebSocket

        config = Config()
        config.grpc.enabled = False
        config.metrics.enabled = False
        server = LightServer(config)

        state = HTTPState(
            registry=server.registry,
            transport=server.transport,
            config=server.config,
            response_queue_id=0,
            repo_path=server.config.model_repository.path,
            log_queue=server._log_queue,
            metrics_dir=server._metrics_dir,
            model_manager=server.model_manager,
        )
        state.init_worker_locals()

        called = {}

        async def mock_close(**kw):
            called["close"] = kw

        async def mock_accept():
            pass

        ws = MagicMock(spec=WebSocket)
        ws.close = mock_close
        ws.accept = mock_accept

        # Pre-register a ready model so validation passes
        state.registry.register("my_model", "1", {}, model_type="litapi")
        state.registry.set_status("my_model", "1", "READY")
        state.registry.activate_version("my_model", "1")

        # Patch submit_stream_open to raise QueueFullError
        _orig_submit_stream_open = submit_stream_open
        import light_server.http.handlers as _handlers_mod

        def _mock_submit_stream_open(*args, **kwargs):
            raise QueueFullError("Queue full")

        _handlers_mod.submit_stream_open = _mock_submit_stream_open

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                _do_ws_stream(state, "my_model", None, ws)
            )
        finally:
            _handlers_mod.submit_stream_open = _orig_submit_stream_open
            loop.close()
        assert "close" in called
        assert "full" in called["close"].get("reason", "").lower()
