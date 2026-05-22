"""HTTP inference handlers with async transport response handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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
        if not server.registry.is_ready(model_name):
            raise HTTPException(status_code=404, detail=f"Model {model_name} not ready")

        payload = await request.json()

        try:
            uid = server.model_manager.infer(model_name, payload, response_queue_id=0)

            # Create event and wait for response
            event = asyncio.Event()
            server.response_buffer[uid] = ResponseBufferItem(event=event)

            await asyncio.wait_for(event.wait(), timeout=server.config.server.timeout)

            response_item = server.response_buffer.pop(uid)
            response_data, status = response_item.response

            if status == LitAPIStatus.ERROR:
                raise HTTPException(status_code=500, detail="Inference error")

            return JSONResponse(response_data)

        except asyncio.TimeoutError:
            server.response_buffer.pop(uid, None)
            raise HTTPException(status_code=504, detail="Inference timeout")
        except Exception as e:
            logger.exception(f"Inference error for {model_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))


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
