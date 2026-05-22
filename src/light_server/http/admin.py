"""Admin API routes for model management."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Query
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
    async def model_ready(model_name: str, version: str | None = Query(None)) -> JSONResponse:
        """Check if a model (or specific version) is ready."""
        ready = server.registry.is_ready(model_name, version)
        active_version = server.registry.get_active_version(model_name)
        return JSONResponse({
            "name": model_name,
            "version": version or active_version,
            "ready": ready,
            "active_version": active_version,
        })

    @app.get("/v2/models/{model_name}/versions")
    async def list_versions(model_name: str) -> JSONResponse:
        """List all loaded versions for a model."""
        versions = server.registry.list_versions(model_name)
        active = server.registry.get_active_version(model_name)
        return JSONResponse({
            "name": model_name,
            "active_version": active,
            "versions": versions,
        })

    @app.post("/v2/repository/index")
    async def repository_index() -> JSONResponse:
        """List available models in the repository."""
        models = server.model_manager.list_repository()
        return JSONResponse({"models": models})

    @app.post("/v2/repository/models/{model_name}/load")
    async def load_model(model_name: str, version: str = Query("1")) -> JSONResponse:
        """Load a specific version of a model from the repository."""
        success = server.model_manager.load(model_name, version=version)
        if success:
            return JSONResponse({
                "success": True,
                "message": f"Model {model_name} version {version} loaded",
            })
        raise HTTPException(status_code=400, detail=f"Failed to load model {model_name} version {version}")

    @app.post("/v2/repository/models/{model_name}/unload")
    async def unload_model(model_name: str, version: str | None = Query(None)) -> JSONResponse:
        """Unload a model. If version is specified, unload that version only."""
        success = server.model_manager.unload(model_name, version=version)
        if success:
            msg = f"Model {model_name}"
            if version:
                msg += f" version {version}"
            msg += " unloaded"
            return JSONResponse({"success": True, "message": msg})
        raise HTTPException(status_code=400, detail=f"Failed to unload model {model_name}")

    @app.post("/v2/models/{model_name}/versions/{version}/activate")
    async def activate_version(model_name: str, version: str) -> JSONResponse:
        """Activate a specific version for default inference routing."""
        success = server.model_manager.activate(model_name, version)
        if success:
            return JSONResponse({
                "success": True,
                "message": f"Model {model_name} version {version} is now active",
                "active_version": version,
            })
        raise HTTPException(status_code=400, detail=f"Model {model_name} version {version} is not ready")
