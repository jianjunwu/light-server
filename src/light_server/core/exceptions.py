"""Unified exception hierarchy for light_server.

All business errors inherit from LightServerError and carry:
- code: machine-readable error code string
- status_code: HTTP status code
- grpc_code: gRPC status code name

This allows centralized exception handling across HTTP, gRPC, and WebSocket.
"""

from __future__ import annotations


class LightServerError(Exception):
    """Base exception for all light_server business errors."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    grpc_code: str = "INTERNAL"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code.replace("_", " ").lower())


class ValidationError(LightServerError):
    """Invalid input (model name, version, payload, etc.)."""

    code = "VALIDATION_ERROR"
    status_code = 400
    grpc_code = "INVALID_ARGUMENT"


class ModelNotFoundError(LightServerError):
    """Model or version not found in registry."""

    code = "MODEL_NOT_FOUND"
    status_code = 404
    grpc_code = "NOT_FOUND"


class ModelNotReadyError(LightServerError):
    """Model exists but is not in READY state."""

    code = "MODEL_NOT_READY"
    status_code = 404
    grpc_code = "UNAVAILABLE"


class QueueFullError(LightServerError):
    """Model request queue is at capacity."""

    code = "QUEUE_FULL"
    status_code = 429
    grpc_code = "UNAVAILABLE"


class InferenceTimeoutError(LightServerError):
    """Inference did not complete within the configured timeout."""

    code = "INFERENCE_TIMEOUT"
    status_code = 504
    grpc_code = "DEADLINE_EXCEEDED"


class EnsembleError(LightServerError):
    """Ensemble DAG execution failed."""

    code = "ENSEMBLE_ERROR"
    status_code = 500
    grpc_code = "INTERNAL"


class WorkerCrashedError(LightServerError):
    """Worker process crashed during inference."""

    code = "WORKER_CRASHED"
    status_code = 500
    grpc_code = "INTERNAL"


class PayloadDecodeError(LightServerError):
    """Failed to decode request payload (e.g. invalid JSON)."""

    code = "PAYLOAD_DECODE_ERROR"
    status_code = 400
    grpc_code = "INVALID_ARGUMENT"
