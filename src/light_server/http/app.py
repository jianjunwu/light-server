"""FastAPI application builder."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from light_server.core.server import LightServer


def create_app(server: LightServer) -> FastAPI:
    app = FastAPI(title="Light Server", version="0.1.0")

    # Health check
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

    return app
