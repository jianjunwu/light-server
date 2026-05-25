"""Tests for model hooks (on_request, on_response, health_check) and dynamic endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

from pathlib import Path

from light_server.core.loader import load_module_from_file
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry
from light_server.http.state import HTTPState


# ------------------------------------------------------------------
# Unit tests for load_module_from_file
# ------------------------------------------------------------------

class TestLoadModuleFromFile:
    def test_loads_module_with_handler(self, tmp_path):
        mod_file = tmp_path / "my_endpoint.py"
        mod_file.write_text(
            "def handler(request, server):\n"
            "    return {'status': 'ok'}\n"
        )
        module = load_module_from_file(mod_file)
        assert hasattr(module, "handler")
        assert module.handler(None, None) == {"status": "ok"}

    def test_loads_module_with_methods(self, tmp_path):
        mod_file = tmp_path / "custom_endpoint.py"
        mod_file.write_text(
            "methods = ['GET', 'POST']\n"
            "def handler(request, server):\n"
            "    return {'ok': True}\n"
        )
        module = load_module_from_file(mod_file)
        assert module.methods == ["GET", "POST"]

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_module_from_file(tmp_path / "missing.py")


# ------------------------------------------------------------------
# Unit tests for ModelManager dynamic endpoints
# ------------------------------------------------------------------

class TestDynamicEndpoints:
    def test_scans_endpoint_files(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)

        # Create endpoint files
        (tmp_path / "health_endpoint.py").write_text(
            "def handler(request, server):\n"
            "    return {'status': 'healthy'}\n"
        )
        (tmp_path / "metrics_endpoint.py").write_text(
            "methods = ['POST']\n"
            "def handler(request, server):\n"
            "    return {'metrics': []}\n"
        )
        # File without handler is ignored
        (tmp_path / "bad_endpoint.py").write_text("x = 1\n")

        endpoints = mgr.load_dynamic_endpoints()
        assert "health" in endpoints
        assert "metrics" in endpoints
        assert "bad" not in endpoints

        assert endpoints["health"]["methods"] == ["GET"]
        assert endpoints["metrics"]["methods"] == ["POST"]

        # Cached on second call
        assert mgr.load_dynamic_endpoints() is endpoints

    def test_empty_repo_returns_empty(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)
        assert mgr.load_dynamic_endpoints() == {}


# ------------------------------------------------------------------
# Unit tests for ModelManager.get_litapi
# ------------------------------------------------------------------

class TestGetLitapi:
    def test_returns_none_when_not_loaded(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)
        assert mgr.get_litapi("missing", "1") is None

    def test_returns_instance_when_loaded(self, tmp_path):
        registry = ModelRegistry()
        mgr = ModelManager(repo_path=tmp_path, registry=registry)

        lit_api = MagicMock()
        mgr._litapi_instances["my_model_1"] = lit_api
        registry.register("my_model", "1", {})
        registry.set_status("my_model", "1", "READY")
        registry.activate_version("my_model", "1")

        assert mgr.get_litapi("my_model", None) is lit_api
        assert mgr.get_litapi("my_model", "1") is lit_api


# ------------------------------------------------------------------
# Integration tests for on_request / on_response hooks
# ------------------------------------------------------------------

class TestModelHooks:
    @pytest.fixture
    def state(self):
        from light_server.core.server import LightServer
        from light_server.config import Config

        config = Config()
        config.grpc.enabled = False
        config.metrics.enabled = False
        config.model_repository.path = "/tmp/test_repo"
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
        return http_state

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_on_request_injects_meta(self, state):
        from light_server.http.handlers import _do_infer
        from light_server.core.model_manager import submit_infer
        from litserve.utils import ResponseBufferItem, LitAPIStatus

        async def mock_json():
            return {"input": 42}

        req = MagicMock(spec=Request)
        req.json = mock_json
        req.headers = {"authorization": "Bearer token123"}
        req.query_params = {"debug": "1"}
        req.client = MagicMock(host="1.2.3.4")
        req.method = "POST"
        req.url = "http://localhost/v2/models/my_model/infer"

        # Setup model registry
        state.registry.register("my_model", "1", {})
        state.registry.set_status("my_model", "1", "READY")
        state.registry.activate_version("my_model", "1")

        # Setup litapi with on_request hook (no on_response)
        lit_api = MagicMock(spec=["on_request"])
        lit_api.on_request = MagicMock(return_value={"input": 42, "_injected": True})

        # Mock submit_infer to avoid worker queue
        uid = "uid-1"

        event = asyncio.Event()
        event.set()
        item = ResponseBufferItem(event=event)
        item.response = ({"output": 99}, LitAPIStatus.OK)

        with patch("light_server.http.handlers.asyncio.Event", return_value=event):
            with patch("light_server.http.handlers.submit_infer", return_value=uid):
                with patch("light_server.http.handlers.ResponseBufferItem", return_value=item):
                    with patch.object(state, "get_litapi_hooks", return_value=lit_api):
                        result = self._run(_do_infer(state, "my_model", None, req))
        assert result.status_code == 200

        # Verify on_request was called with correct meta
        call_args = lit_api.on_request.call_args
        payload, meta = call_args[0]
        assert payload == {"input": 42}
        assert meta["headers"]["authorization"] == "Bearer token123"
        assert meta["query_params"]["debug"] == "1"
        assert meta["client_host"] == "1.2.3.4"
        assert meta["method"] == "POST"

    def test_on_response_enhances_output(self, state):
        from light_server.http.handlers import _do_litapi_infer
        from litserve.utils import ResponseBufferItem, LitAPIStatus

        # Setup model registry
        state.registry.register("my_model", "1", {})
        state.registry.set_status("my_model", "1", "READY")

        # Setup litapi with on_response hook
        lit_api = MagicMock()
        lit_api.on_response = MagicMock(return_value={"output": 99, "extra": "data"})

        uid = "uid-2"

        event = asyncio.Event()
        event.set()
        item = ResponseBufferItem(event=event)
        item.response = ({"output": 99}, LitAPIStatus.OK)

        request_meta = {"client_host": "1.2.3.4"}
        with patch("light_server.http.handlers.asyncio.Event", return_value=event):
            with patch("light_server.http.handlers.submit_infer", return_value=uid):
                with patch("light_server.http.handlers.ResponseBufferItem", return_value=item):
                    with patch.object(state, "get_litapi_hooks", return_value=lit_api):
                        result = self._run(_do_litapi_infer(state, "my_model", "1", {"input": 42}, request_meta))
        assert result.status_code == 200

        # Verify on_response was called
        call_args = lit_api.on_response.call_args
        response, meta = call_args[0]
        assert response == {"output": 99}
        assert meta["model_name"] == "my_model"
        assert meta["status"] == "ok"
        assert meta["request_meta"]["client_host"] == "1.2.3.4"

    def test_on_response_error_ignored(self, state):
        from light_server.http.handlers import _do_litapi_infer
        from litserve.utils import ResponseBufferItem, LitAPIStatus

        state.registry.register("my_model", "1", {})
        state.registry.set_status("my_model", "1", "READY")

        lit_api = MagicMock()
        lit_api.on_response = MagicMock(side_effect=RuntimeError("boom"))

        uid = "uid-3"

        event = asyncio.Event()
        event.set()
        item = ResponseBufferItem(event=event)
        item.response = ({"output": 99}, LitAPIStatus.OK)

        # Should not raise even though on_response fails
        with patch("light_server.http.handlers.asyncio.Event", return_value=event):
            with patch("light_server.http.handlers.submit_infer", return_value=uid):
                with patch("light_server.http.handlers.ResponseBufferItem", return_value=item):
                    with patch.object(state, "get_litapi_hooks", return_value=lit_api):
                        result = self._run(_do_litapi_infer(state, "my_model", "1", {"input": 42}))
        assert result.status_code == 200

    def test_no_hooks_no_error(self, state):
        from light_server.http.handlers import _do_litapi_infer
        from litserve.utils import ResponseBufferItem, LitAPIStatus

        state.registry.register("my_model", "1", {})
        state.registry.set_status("my_model", "1", "READY")

        lit_api = MagicMock(spec=[])  # no hooks at all

        uid = "uid-4"

        event = asyncio.Event()
        event.set()
        item = ResponseBufferItem(event=event)
        item.response = ({"output": 99}, LitAPIStatus.OK)

        with patch("light_server.http.handlers.asyncio.Event", return_value=event):
            with patch("light_server.http.handlers.submit_infer", return_value=uid):
                with patch("light_server.http.handlers.ResponseBufferItem", return_value=item):
                    with patch.object(state, "get_litapi_hooks", return_value=lit_api):
                        result = self._run(_do_litapi_infer(state, "my_model", "1", {"input": 42}))
        assert result.status_code == 200


# ------------------------------------------------------------------
# Integration tests for /v2/models/{name}/ready with health_check
# ------------------------------------------------------------------

class TestModelReadyHealthCheck:
    def _make_state(self):
        from light_server.core.server import LightServer
        from light_server.config import Config
        from fastapi import FastAPI

        config = Config()
        config.grpc.enabled = False
        config.metrics.enabled = False
        server = LightServer(config)
        state = HTTPState(
            registry=server.registry,
            transport=server.transport,
            config=server.config,
            response_queue_id=0,
            repo_path=Path(server.config.model_repository.path),
            log_queue=server._log_queue,
            metrics_dir=server._metrics_dir,
            model_manager=server.model_manager,
        )
        state.init_worker_locals()
        return state

    def test_ready_includes_model_status(self):
        from light_server.http.admin import create_admin_routes
        from fastapi import FastAPI

        state = self._make_state()

        state.registry.register("my_model", "1", {})
        state.registry.set_status("my_model", "1", "READY")
        state.registry.activate_version("my_model", "1")

        lit_api = MagicMock()
        lit_api.health_check = MagicMock(return_value={"status": "healthy", "gpu": 0.5})

        app = FastAPI()
        create_admin_routes(app, state)

        from fastapi.testclient import TestClient
        client = TestClient(app)
        with patch.object(state, "get_litapi_hooks", return_value=lit_api):
            resp = client.get("/v2/models/my_model/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is True
        assert data["model_status"]["status"] == "healthy"
        assert data["model_status"]["gpu"] == 0.5

    def test_ready_without_health_check(self):
        from light_server.http.admin import create_admin_routes
        from fastapi import FastAPI

        state = self._make_state()

        state.registry.register("my_model", "1", {})
        state.registry.set_status("my_model", "1", "READY")

        # No health_check on lit_api
        lit_api = MagicMock(spec=[])

        app = FastAPI()
        create_admin_routes(app, state)

        from fastapi.testclient import TestClient
        client = TestClient(app)
        with patch.object(state, "get_litapi_hooks", return_value=lit_api):
            resp = client.get("/v2/models/my_model/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert "model_status" not in data

    def test_ready_health_check_error_graceful(self):
        from light_server.http.admin import create_admin_routes
        from fastapi import FastAPI

        state = self._make_state()

        state.registry.register("my_model", "1", {})
        state.registry.set_status("my_model", "1", "READY")
        state.registry.activate_version("my_model", "1")

        lit_api = MagicMock()
        lit_api.health_check = MagicMock(side_effect=RuntimeError("gpu not ready"))

        app = FastAPI()
        create_admin_routes(app, state)

        from fastapi.testclient import TestClient
        client = TestClient(app)
        with patch.object(state, "get_litapi_hooks", return_value=lit_api):
            resp = client.get("/v2/models/my_model/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_status"]["status"] == "error"
        assert "gpu not ready" in data["model_status"]["error"]


# ------------------------------------------------------------------
# Integration tests for dynamic endpoints in create_app
# ------------------------------------------------------------------

class TestDynamicEndpointRegistration:
    def _make_state(self, repo_path: Path):
        from light_server.core.server import LightServer
        from light_server.config import Config

        config = Config()
        config.grpc.enabled = False
        config.metrics.enabled = False
        config.model_repository.path = str(repo_path)
        server = LightServer(config)
        state = HTTPState(
            registry=server.registry,
            transport=server.transport,
            config=server.config,
            response_queue_id=0,
            repo_path=Path(server.config.model_repository.path),
            log_queue=server._log_queue,
            metrics_dir=server._metrics_dir,
            model_manager=server.model_manager,
        )
        state.init_worker_locals()
        return state

    def test_health_endpoint_overrides_default(self, tmp_path):
        from light_server.http.app import create_app

        # Write health_endpoint.py
        (tmp_path / "health_endpoint.py").write_text(
            "def handler(request, server):\n"
            "    return {'custom': True}\n"
        )

        state = self._make_state(tmp_path)
        app = create_app(state)

        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["custom"] is True

    def test_async_endpoint(self, tmp_path):
        from light_server.http.app import create_app

        (tmp_path / "status_endpoint.py").write_text(
            "async def handler(request, server):\n"
            "    return {'async': True}\n"
        )

        state = self._make_state(tmp_path)
        app = create_app(state)

        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/status")
        assert resp.status_code == 200
        assert resp.json()["async"] is True

    def test_post_endpoint(self, tmp_path):
        from light_server.http.app import create_app

        (tmp_path / "webhook_endpoint.py").write_text(
            "methods = ['POST']\n"
            "def handler(request, server):\n"
            "    return {'webhook': True}\n"
        )

        state = self._make_state(tmp_path)
        app = create_app(state)

        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.post("/webhook")
        assert resp.status_code == 200
        assert resp.json()["webhook"] is True

    def test_default_health_when_no_endpoint_file(self, tmp_path):
        from light_server.http.app import create_app

        state = self._make_state(tmp_path)
        app = create_app(state)

        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.text == "ok"
