"""FastAPI application builder."""

from __future__ import annotations

import inspect
import logging
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from light_server.core.exceptions import LightServerError
from light_server.core.response import error_response
from light_server.core.server import LightServer

logger = logging.getLogger(__name__)


async def lightserver_exception_handler(request: Request, exc: LightServerError) -> JSONResponse:
    """Handle all LightServerError subclasses with a standardized JSON envelope."""
    return error_response(exc)


async def fallback_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions; returns a generic 500 envelope."""
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "Internal server error"}},
    )


def create_app(server: LightServer) -> FastAPI:
    app = FastAPI(title="Light Server", version="0.1.0")

    app.add_exception_handler(LightServerError, lightserver_exception_handler)
    app.add_exception_handler(Exception, fallback_exception_handler)

    # 1. Register dynamic endpoints from model_repo/*_endpoint.py
    endpoints = server.model_manager.load_dynamic_endpoints()

    def _wrap_async_handler(h):
        async def _handler(request: Request) -> JSONResponse:
            result = await h(request, server)
            return JSONResponse(result)
        return _handler

    def _wrap_sync_handler(h):
        def _handler(request: Request) -> JSONResponse:
            result = h(request, server)
            return JSONResponse(result)
        return _handler

    for route, ep in endpoints.items():
        handler = ep["handler"]
        methods = ep["methods"]
        if inspect.iscoroutinefunction(handler):
            app.add_api_route(f"/{route}", _wrap_async_handler(handler), methods=methods)
        else:
            app.add_api_route(f"/{route}", _wrap_sync_handler(handler), methods=methods)

    # 2. Default /health if not overridden by dynamic endpoint
    if "health" not in endpoints:
        @app.get("/health")
        async def health() -> Response:
            return Response(content="ok", status_code=200)

    # Info
    @app.get("/info")
    async def info() -> JSONResponse:
        return JSONResponse({
            "server": "light-server",
            "version": "0.1.0",
            "loaded_models": server.registry.list_loaded(),
        })

    # Admin routes
    from light_server.http.admin import create_admin_routes
    create_admin_routes(app, server)

    # Inference routes
    from light_server.http.handlers import create_inference_routes
    create_inference_routes(app, server)

    # Web UI routes (only if enabled)
    if server.config.webui.enabled:
        from light_server.webui.routes import create_ui_routes
        create_ui_routes(app, server)

    return app
