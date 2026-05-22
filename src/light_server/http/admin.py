"""Admin API routes for model management."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from light_server.core.server import LightServer

logger = logging.getLogger(__name__)


def create_admin_routes(app: FastAPI, server: LightServer) -> None:
    """Register admin routes on the FastAPI app."""

    @app.get("/v2/models")
    async def list_models() -> JSONResponse:
        """List loaded models."""
        models = server.registry.list_loaded()
        return JSONResponse({"models": models})

    @app.get("/v2/models/{model_name}/ready")
    async def model_ready(model_name: str) -> JSONResponse:
        """Check if a model is ready."""
        ready = server.registry.is_ready(model_name)
        return JSONResponse({"name": model_name, "ready": ready})

    @app.post("/v2/repository/index")
    async def repository_index() -> JSONResponse:
        """List available models in the repository."""
        models = server.model_manager.list_repository()
        return JSONResponse({"models": models})

    @app.post("/v2/repository/models/{model_name}/load")
    async def load_model(model_name: str) -> JSONResponse:
        """Load a model from the repository."""
        success = server.model_manager.load(model_name)
        if success:
            return JSONResponse({"success": True, "message": f"Model {model_name} loaded"})
        raise HTTPException(status_code=400, detail=f"Failed to load model {model_name}")

    @app.post("/v2/repository/models/{model_name}/unload")
    async def unload_model(model_name: str) -> JSONResponse:
        """Unload a model."""
        success = server.model_manager.unload(model_name)
        if success:
            return JSONResponse({"success": True, "message": f"Model {model_name} unloaded"})
        raise HTTPException(status_code=400, detail=f"Failed to unload model {model_name}")
