"""Tests for bounded request queue / DoS prevention."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from light_server.core.model_manager import ModelManager, QueueFullError
from light_server.core.registry import ModelRegistry


class TestQueueFullError:
    def test_infer_raises_when_queue_full(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)

        # Manually set up a ready model with a tiny queue
        registry.register("test_model", "1", {"max_queue_size": 2}, model_type="litapi")
        registry.set_status("test_model", "1", "READY")
        registry.activate_version("test_model", "1")
        tiny_queue = mp.Queue(maxsize=2)
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
        q = mp.Queue(maxsize=10)
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
        tiny_queue = mp.Queue(maxsize=1)
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
        tiny_queue = mp.Queue(maxsize=1)
        registry.set_worker_queues("test_model", "1", [tiny_queue])

        # Pre-register stream routing so chunk can be sent
        mgr._stream_routing["stream-1"] = 0
        tiny_queue.put_nowait((0, "uid-1", 0.0, {"x": 1}))

        with pytest.raises(QueueFullError):
            mgr.infer_stream_chunk("test_model", "stream-1", {"data": "chunk"})


class TestHTTPQueueLimit:
    def test_infer_handler_returns_429_on_queue_full(self):
        from light_server.http.handlers import _do_litapi_infer
        from light_server.core.server import LightServer
        from light_server.config import Config
        from light_server.core.model_manager import QueueFullError

        config = Config()
        config.grpc.enabled = False
        config.metrics.enabled = False
        server = LightServer(config)

        # Patch infer to always raise QueueFullError
        server.model_manager.infer = lambda *args, **kwargs: (_ for _ in ()).throw(
            QueueFullError("Queue full")
        )

        with pytest.raises(HTTPException) as exc_info:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    _do_litapi_infer(server, "my_model", None, {"x": 1})
                )
            finally:
                loop.close()
        assert exc_info.value.status_code == 429
        assert "full" in exc_info.value.detail.lower()

    def test_ws_stream_handler_closes_on_queue_full(self):
        from light_server.http.handlers import _do_ws_stream
        from light_server.core.server import LightServer
        from light_server.config import Config
        from light_server.core.model_manager import QueueFullError
        from fastapi import WebSocket

        config = Config()
        config.grpc.enabled = False
        config.metrics.enabled = False
        server = LightServer(config)

        called = {}

        async def mock_close(**kw):
            called["close"] = kw

        async def mock_accept():
            pass

        ws = MagicMock(spec=WebSocket)
        ws.close = mock_close
        ws.accept = mock_accept

        # Pre-register a ready model so validation passes
        server.registry.register("my_model", "1", {}, model_type="litapi")
        server.registry.set_status("my_model", "1", "READY")
        server.registry.activate_version("my_model", "1")

        # Patch infer_stream_open to raise QueueFullError
        server.model_manager.infer_stream_open = lambda *args, **kwargs: (_ for _ in ()).throw(
            QueueFullError("Queue full")
        )

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                _do_ws_stream(server, "my_model", None, ws)
            )
        finally:
            loop.close()
        assert "close" in called
        assert "full" in called["close"].get("reason", "").lower()
