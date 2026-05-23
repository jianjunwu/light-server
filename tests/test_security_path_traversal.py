"""Tests for path traversal prevention in model name / version handling."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from light_server.core.validation import validate_model_name, validate_version
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry


# ------------------------------------------------------------------
# Unit tests for validation functions
# ------------------------------------------------------------------

class TestValidationFunctions:
    def test_valid_model_names(self):
        for name in ["model", "model_1", "my-model", "A1_b2-c3", "x" * 64]:
            validate_model_name(name)  # should not raise

    def test_invalid_model_names(self):
        invalid = [
            "",
            "model/name",
            "model\\name",
            "model..name",
            "../etc",
            "model%00",
            "model:name",
            "model@name",
            "x" * 65,
            "model.name",  # dot not allowed in model name
        ]
        for name in invalid:
            with pytest.raises(ValueError):
                validate_model_name(name)

    def test_valid_versions(self):
        for v in ["1", "1.0", "1.0.2", "v1", "latest", "x" * 32]:
            validate_version(v)  # should not raise

    def test_invalid_versions(self):
        invalid = [
            "",
            "1/0",
            "1\\0",
            "../etc",
            "v1%00",
            "x" * 33,
        ]
        for v in invalid:
            with pytest.raises(ValueError):
                validate_version(v)


# ------------------------------------------------------------------
# Unit tests for ModelManager boundary checks
# ------------------------------------------------------------------

class TestModelManagerPathBoundary:
    def test_load_rejects_path_traversal(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)
        # These should return False (not raise unhandled exception)
        assert mgr.load("../etc/passwd", "1") is False
        assert mgr.load("model", "../../../etc") is False
        assert mgr.load("model", "..\\windows") is False

    def test_unload_rejects_path_traversal(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)
        assert mgr.unload("../etc/passwd", "1") is False
        assert mgr.unload("model", "../../../etc") is False

    def test_resolve_model_base_enforces_boundary(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)
        # Normal case
        base = mgr._resolve_model_base("my_model")
        assert str(base).startswith(str(tmp_path.resolve()))

        # Path traversal should raise ValueError
        with pytest.raises(ValueError):
            mgr._resolve_model_base("../outside")
        with pytest.raises(ValueError):
            mgr._resolve_model_base("model/../../outside")


# ------------------------------------------------------------------
# Integration tests for HTTP handlers (call async functions directly
# because TestClient normalises %2F away)
# ------------------------------------------------------------------

import asyncio


class TestHTTPPathTraversal:
    @pytest.fixture
    def server(self):
        from light_server.core.server import LightServer
        from light_server.config import Config

        config = Config()
        config.grpc.enabled = False
        config.metrics.enabled = False
        config.model_repository.path = "/tmp/test_repo"
        return LightServer(config)

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_infer_handler_rejects_traversal_name(self, server):
        from light_server.http.handlers import _do_infer
        from fastapi import Request, HTTPException

        async def mock_json():
            return {"x": 1}

        req = MagicMock(spec=Request)
        req.json = mock_json

        with pytest.raises(HTTPException) as exc_info:
            self._run(_do_infer(server, "../../etc/passwd", None, req))
        assert exc_info.value.status_code == 400

    def test_infer_handler_rejects_traversal_version(self, server):
        from light_server.http.handlers import _do_infer
        from fastapi import Request, HTTPException

        async def mock_json():
            return {"x": 1}

        req = MagicMock(spec=Request)
        req.json = mock_json

        with pytest.raises(HTTPException) as exc_info:
            self._run(_do_infer(server, "my_model", "../../../etc", req))
        assert exc_info.value.status_code == 400

    def test_ws_stream_handler_rejects_traversal_name(self, server):
        from light_server.http.handlers import _do_ws_stream
        from fastapi import WebSocket

        called = {}

        async def mock_accept():
            called["accept"] = True

        async def mock_close(**kw):
            called["close"] = kw

        ws = MagicMock(spec=WebSocket)
        ws.accept = mock_accept
        ws.close = mock_close

        self._run(_do_ws_stream(server, "../../etc/passwd", None, ws))
        assert "close" in called

    def test_admin_load_rejects_traversal(self, server):
        from light_server.http.admin import create_admin_routes
        from fastapi import FastAPI, HTTPException

        app = FastAPI()
        create_admin_routes(app, server)

        # Call the route function directly
        for route in app.routes:
            if getattr(route, "path", None) == "/v2/repository/models/{model_name}/load":
                with pytest.raises(HTTPException) as exc_info:
                    self._run(route.endpoint("../../etc", "1"))
                assert exc_info.value.status_code == 400
                return
        pytest.fail("load route not found")

    def test_admin_unload_rejects_traversal(self, server):
        from light_server.http.admin import create_admin_routes
        from fastapi import FastAPI, HTTPException

        app = FastAPI()
        create_admin_routes(app, server)

        for route in app.routes:
            if getattr(route, "path", None) == "/v2/repository/models/{model_name}/unload":
                with pytest.raises(HTTPException) as exc_info:
                    self._run(route.endpoint("../../etc", "1"))
                assert exc_info.value.status_code == 400
                return
        pytest.fail("unload route not found")

    def test_admin_activate_rejects_traversal(self, server):
        from light_server.http.admin import create_admin_routes
        from fastapi import FastAPI, HTTPException

        app = FastAPI()
        create_admin_routes(app, server)

        for route in app.routes:
            if getattr(route, "path", None) == "/v2/models/{model_name}/versions/{version}/activate":
                with pytest.raises(HTTPException) as exc_info:
                    self._run(route.endpoint("../../etc", "1"))
                assert exc_info.value.status_code == 400
                return
        pytest.fail("activate route not found")

    def test_admin_ready_rejects_traversal(self, server):
        from light_server.http.admin import create_admin_routes
        from fastapi import FastAPI, HTTPException

        app = FastAPI()
        create_admin_routes(app, server)

        for route in app.routes:
            if getattr(route, "path", None) == "/v2/models/{model_name}/ready":
                with pytest.raises(HTTPException) as exc_info:
                    self._run(route.endpoint("../../etc", None))
                assert exc_info.value.status_code == 400
                return
        pytest.fail("ready route not found")

    def test_admin_versions_rejects_traversal(self, server):
        from light_server.http.admin import create_admin_routes
        from fastapi import FastAPI, HTTPException

        app = FastAPI()
        create_admin_routes(app, server)

        for route in app.routes:
            if getattr(route, "path", None) == "/v2/models/{model_name}/versions":
                with pytest.raises(HTTPException) as exc_info:
                    self._run(route.endpoint("../../etc"))
                assert exc_info.value.status_code == 400
                return
        pytest.fail("versions route not found")
