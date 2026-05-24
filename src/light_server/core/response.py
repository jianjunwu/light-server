"""Standardized error response helpers."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from light_server.core.exceptions import LightServerError


def error_response(exc: LightServerError) -> JSONResponse:
    """Build a standardized JSON error response from a LightServerError."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": str(exc),
            }
        },
    )


def error_dict(code: str, message: str) -> dict[str, Any]:
    """Build a raw error dict for non-HTTP transports (WebSocket, internal)."""
    return {"error": {"code": code, "message": message}}
