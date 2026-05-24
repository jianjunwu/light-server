"""Tests for unified exception hierarchy and centralized error handling."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from light_server.core.exceptions import (
    EnsembleError,
    InferenceTimeoutError,
    LightServerError,
    ModelNotFoundError,
    ModelNotReadyError,
    PayloadDecodeError,
    QueueFullError,
    ValidationError,
    WorkerCrashedError,
)
from light_server.core.response import error_dict, error_response
from light_server.http.app import create_app
from light_server.core.server import LightServer
from light_server.config import Config


# ------------------------------------------------------------------
# Exception class tests
# ------------------------------------------------------------------

class TestExceptionAttributes:
    def test_base_error_defaults(self):
        exc = LightServerError("something went wrong")
        assert exc.code == "INTERNAL_ERROR"
        assert exc.status_code == 500
        assert exc.grpc_code == "INTERNAL"
        assert str(exc) == "something went wrong"

    def test_validation_error(self):
        exc = ValidationError("bad input")
        assert exc.code == "VALIDATION_ERROR"
        assert exc.status_code == 400
        assert exc.grpc_code == "INVALID_ARGUMENT"

    def test_model_not_found(self):
        exc = ModelNotFoundError("model xyz not found")
        assert exc.code == "MODEL_NOT_FOUND"
        assert exc.status_code == 404
        assert exc.grpc_code == "NOT_FOUND"

    def test_model_not_ready(self):
        exc = ModelNotReadyError("model not ready")
        assert exc.code == "MODEL_NOT_READY"
        assert exc.status_code == 404
        assert exc.grpc_code == "UNAVAILABLE"

    def test_queue_full(self):
        exc = QueueFullError("queue is full")
        assert exc.code == "QUEUE_FULL"
        assert exc.status_code == 429
        assert exc.grpc_code == "UNAVAILABLE"

    def test_inference_timeout(self):
        exc = InferenceTimeoutError("timed out")
        assert exc.code == "INFERENCE_TIMEOUT"
        assert exc.status_code == 504
        assert exc.grpc_code == "DEADLINE_EXCEEDED"

    def test_ensemble_error(self):
        exc = EnsembleError("DAG failed")
        assert exc.code == "ENSEMBLE_ERROR"
        assert exc.status_code == 500
        assert exc.grpc_code == "INTERNAL"

    def test_worker_crashed(self):
        exc = WorkerCrashedError("worker died")
        assert exc.code == "WORKER_CRASHED"
        assert exc.status_code == 500
        assert exc.grpc_code == "INTERNAL"

    def test_payload_decode_error(self):
        exc = PayloadDecodeError("invalid json")
        assert exc.code == "PAYLOAD_DECODE_ERROR"
        assert exc.status_code == 400
        assert exc.grpc_code == "INVALID_ARGUMENT"

    def test_default_message(self):
        """If no message is provided, use a readable version of the code."""
        exc = ValidationError()
        assert str(exc) == "validation error"


# ------------------------------------------------------------------
# Response helper tests
# ------------------------------------------------------------------

class TestErrorResponse:
    def test_error_response_structure(self):
        exc = ValidationError("field required")
        resp = error_response(exc)
        assert resp.status_code == 400
        assert resp.body == b'{"error":{"code":"VALIDATION_ERROR","message":"field required"}}'

    def test_error_dict(self):
        d = error_dict("FOO_ERROR", "bar")
        assert d == {"error": {"code": "FOO_ERROR", "message": "bar"}}


# ------------------------------------------------------------------
# Global exception handler tests (via TestClient)
# ------------------------------------------------------------------

class TestGlobalExceptionHandlers:
    @pytest.fixture
    def client(self):
        config = Config()
        config.grpc.enabled = False
        config.metrics.enabled = False
        config.model_repository.path = "/tmp/test_repo"
        server = LightServer(config)
        app = create_app(server)
        return TestClient(app)

    def test_validation_error_returns_400(self, client):
        """Admin routes that reject invalid input should return 400 with error envelope."""
        # Use a path with invalid chars that won't be normalised by the client
        response = client.post("/v2/repository/models/invalid:name/load?version=1")
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "model name" in body["error"]["message"].lower() or "invalid" in body["error"]["message"].lower()

    def test_model_not_ready_returns_404(self, client):
        """Inference against a non-ready model should return 404 with error envelope."""
        response = client.post("/v2/models/nonexistent/infer", json={"x": 1})
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "MODEL_NOT_READY"

    def test_fallback_handler_returns_500(self, client):
        """Unhandled exceptions should return 500 with generic error envelope.

        Starlette does not route bare Exception to user-registered handlers during
        TestClient transport, so we exercise the handler directly.
        """
        from light_server.http.app import fallback_exception_handler
        from unittest.mock import MagicMock

        request = MagicMock()
        exc = RuntimeError("boom")
        response = client.app.dependency_overrides.get(
            fallback_exception_handler,
            lambda: fallback_exception_handler,
        )
        # Directly invoke the async handler (run via anyio in async context)
        import asyncio
        from fastapi import Request
        req = MagicMock(spec=Request)
        resp = asyncio.new_event_loop().run_until_complete(
            fallback_exception_handler(req, exc)
        )
        assert resp.status_code == 500
        body = json.loads(resp.body)
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "internal server error" in body["error"]["message"].lower()
