"""Admin API routes for model management."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from light_server.core.exceptions import ValidationError
from light_server.core.validation import validate_model_name, validate_version
from light_server.http.state import HTTPState

logger = logging.getLogger(__name__)


def create_admin_routes(app: FastAPI, state: HTTPState) -> None:
    """Register admin routes on the FastAPI app."""

    @app.get("/v2/models")
    async def list_models() -> JSONResponse:
        """List loaded models."""
        models = state.registry.list_loaded()
        return JSONResponse({"models": models})

    @app.get("/v2/models/{model_name}/ready")
    async def model_ready(model_name: str, version: str | None = Query(None)) -> JSONResponse:
        """Check if a model (or specific version) is ready."""
        validate_model_name(model_name)
        if version is not None:
            validate_version(version)
        ready = state.registry.is_ready(model_name, version)
        active_version = state.registry.get_active_version(model_name)
        result: dict[str, Any] = {
            "name": model_name,
            "version": version or active_version,
            "ready": ready,
            "active_version": active_version,
        }

        lit_api = state.get_litapi_hooks(model_name, version)
        if lit_api is not None and hasattr(lit_api, "health_check"):
            try:
                result["model_status"] = lit_api.health_check()
            except Exception as e:
                logger.warning(f"health_check failed for {model_name}: {e}")
                result["model_status"] = {"status": "error", "error": str(e)}

        return JSONResponse(result)

    @app.get("/v2/models/{model_name}/versions")
    async def list_versions(model_name: str) -> JSONResponse:
        """List all loaded versions for a model."""
        validate_model_name(model_name)
        versions = state.registry.list_versions(model_name)
        active = state.registry.get_active_version(model_name)
        return JSONResponse({
            "name": model_name,
            "active_version": active,
            "versions": versions,
        })

    @app.post("/v2/repository/index")
    async def repository_index() -> JSONResponse:
        """List available models in the repository."""
        models = state.list_repository()
        return JSONResponse({"models": models})

    @app.post("/v2/repository/models/{model_name}/load")
    async def load_model(model_name: str, version: str = Query("1")) -> JSONResponse:
        """Load a specific version of a model from the repository."""
        validate_model_name(model_name)
        validate_version(version)
        success = await state.load_model(model_name, version)
        if success:
            return JSONResponse({
                "success": True,
                "message": f"Model {model_name} version {version} loaded",
            })
        raise ValidationError(f"Failed to load model {model_name} version {version}")

    @app.post("/v2/repository/models/{model_name}/unload")
    async def unload_model(model_name: str, version: str | None = Query(None)) -> JSONResponse:
        """Unload a model. If version is specified, unload that version only."""
        validate_model_name(model_name)
        if version is not None:
            validate_version(version)
        success = await state.unload_model(model_name, version)
        if success:
            msg = f"Model {model_name}"
            if version:
                msg += f" version {version}"
            msg += " unloaded"
            return JSONResponse({"success": True, "message": msg})
        raise ValidationError(f"Failed to unload model {model_name}")

    @app.post("/v2/models/{model_name}/versions/{version}/activate")
    async def activate_version(model_name: str, version: str) -> JSONResponse:
        """Activate a specific version for default inference routing."""
        validate_model_name(model_name)
        validate_version(version)
        success = await state.activate_model(model_name, version)
        if success:
            return JSONResponse({
                "success": True,
                "message": f"Model {model_name} version {version} is now active",
                "active_version": version,
            })
        raise ValidationError(f"Model {model_name} version {version} is not ready")
