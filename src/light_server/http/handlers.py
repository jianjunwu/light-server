"""HTTP inference handlers with async transport response handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from light_server.core.ensemble import EnsembleExecutor
from light_server.core.server import LightServer
from litserve.utils import LitAPIStatus, ResponseBufferItem

logger = logging.getLogger(__name__)


def create_inference_routes(app: FastAPI, server: LightServer) -> None:
    """Register inference routes on the FastAPI app."""

    @app.on_event("startup")
    async def start_response_consumer() -> None:
        """Start background task to consume responses from transport."""
        asyncio.create_task(_response_consumer(server))

    @app.post("/v2/models/{model_name}/infer")
    async def infer(model_name: str, request: Request) -> JSONResponse:
        """Inference against the active version of a model."""
        return await _do_infer(server, model_name, None, request)

    @app.post("/v2/models/{model_name}/versions/{version}/infer")
    async def infer_version(model_name: str, version: str, request: Request) -> JSONResponse:
        """Inference against a specific version of a model."""
        return await _do_infer(server, model_name, version, request)


async def _do_infer(server: LightServer, model_name: str, version: str | None, request: Request) -> JSONResponse:
    resolved_version = version or server.registry.get_active_version(model_name) or "unknown"
    server.system_metrics.record_request_start(model_name, resolved_version)

    status = "2xx"
    try:
        if not server.registry.is_ready(model_name, version):
            status = "4xx"
            detail = f"Model {model_name}"
            if version:
                detail += f" version {version}"
            detail += " not ready"
            raise HTTPException(status_code=404, detail=detail)

        payload = await request.json()

        entry = server.registry.get(model_name, version)
        if entry is not None and entry.get("model_type") == "ensemble":
            result = await _do_ensemble_infer(server, model_name, version, payload)
        else:
            result = await _do_litapi_infer(server, model_name, version, payload)

        return result

    except HTTPException as e:
        status = "5xx" if e.status_code >= 500 else "4xx"
        raise
    except asyncio.TimeoutError:
        status = "timeout"
        raise
    except Exception:
        status = "5xx"
        raise
    finally:
        server.system_metrics.record_request_end(model_name, resolved_version, status)


async def _do_ensemble_infer(
    server: LightServer, model_name: str, version: str | None, payload: dict[str, Any]
) -> JSONResponse:
    """Execute an ensemble DAG and return the final step's output."""
    entry = server.registry.get(model_name, version)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Model {model_name} not found")

    ensemble_config = entry.get("ensemble_config")
    if ensemble_config is None:
        raise HTTPException(status_code=500, detail="Ensemble config missing")

    try:
        executor = EnsembleExecutor()
        result = await executor.execute(server, ensemble_config, payload, ensemble_name=model_name)
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Ensemble inference error for {model_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _do_litapi_infer(
    server: LightServer, model_name: str, version: str | None, payload: dict[str, Any]
) -> JSONResponse:
    """Submit inference to a LitAPI worker and await response."""
    uid = None
    try:
        uid = server.model_manager.infer(
            model_name, payload, version=version, response_queue_id=0
        )

        event = asyncio.Event()
        server.response_buffer[uid] = ResponseBufferItem(event=event)

        await asyncio.wait_for(
            event.wait(), timeout=server.config.server.timeout
        )

        response_item = server.response_buffer.pop(uid)
        response_data, status = response_item.response

        if status == LitAPIStatus.ERROR:
            raise HTTPException(status_code=500, detail="Inference error")

        return JSONResponse(response_data)

    except asyncio.TimeoutError:
        server.response_buffer.pop(uid, None)
        raise HTTPException(status_code=504, detail="Inference timeout")
    except asyncio.CancelledError:
        server.response_buffer.pop(uid, None)
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Inference error for {model_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if uid is not None:
            resolved_version = version or server.registry.get_active_version(model_name) or "unknown"
            server.system_metrics.dec_queue_depth(model_name, resolved_version)


async def _response_consumer(server: LightServer) -> None:
    """Continuously read responses from transport and signal waiting handlers."""
    transport = server.transport
    while True:
        try:
            result = await transport.areceive(consumer_id=0)
            if result is None:
                continue

            # Format: (uid, (response_data, status, response_type, worker_id))
            uid, (response_data, status, response_type, worker_id) = result

            response_item = server.response_buffer.get(uid)
            if response_item is None:
                continue

            response_item.response = (response_data, status)
            response_item.worker_id = int(worker_id)
            response_item.event.set()

        except asyncio.CancelledError:
            logger.debug("Response consumer cancelled")
            break
        except Exception as e:
            logger.error(f"Error in response consumer: {e}")
