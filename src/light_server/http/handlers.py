"""HTTP inference handlers with async transport response handling."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from light_server.core.ensemble import EnsembleExecutor
from light_server.core.server import LightServer
from litserve.utils import LitAPIStatus, LoopResponseType, ResponseBufferItem

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

    @app.websocket("/v2/models/{model_name}/stream")
    async def ws_stream(model_name: str, websocket: WebSocket) -> None:
        await _do_ws_stream(server, model_name, None, websocket)

    @app.websocket("/v2/models/{model_name}/versions/{version}/stream")
    async def ws_stream_version(model_name: str, version: str, websocket: WebSocket) -> None:
        await _do_ws_stream(server, model_name, version, websocket)


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


async def _do_ws_stream(
    server: LightServer, model_name: str, version: str | None, websocket: WebSocket
) -> None:
    """Handle a bidirectional WebSocket stream."""
    await websocket.accept()

    resolved_version = version or server.registry.get_active_version(model_name) or "unknown"
    server.system_metrics.record_request_start(model_name, resolved_version)

    stream_id: str | None = None
    status = "2xx"
    try:
        if not server.registry.is_ready(model_name, version):
            status = "4xx"
            await websocket.close(code=1011, reason=f"Model {model_name} not ready")
            return

        stream_id = f"ws-{uuid.uuid4().hex}"

        event = asyncio.Event()
        buffer_item = ResponseBufferItem(event=event, response_queue=deque())
        server.response_buffer[stream_id] = buffer_item

        server.model_manager.infer_stream_open(
            model_name, stream_id, version=version, response_queue_id=0
        )

        sender_task = asyncio.create_task(
            _ws_sender(websocket, buffer_item, stream_id),
            name=f"ws-sender-{stream_id}",
        )
        receiver_task = asyncio.create_task(
            _ws_receiver(websocket, server, model_name, stream_id, version),
            name=f"ws-receiver-{stream_id}",
        )

        done, pending = await asyncio.wait(
            [sender_task, receiver_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                raise exc

    except WebSocketDisconnect:
        pass
    except Exception as e:
        status = "5xx"
        logger.exception(f"WebSocket stream error for {model_name}: {e}")
        try:
            await websocket.close(code=1011, reason=str(e))
        except Exception:
            pass
    finally:
        if stream_id is not None:
            try:
                server.model_manager.infer_stream_close(model_name, stream_id, version=version)
            except Exception:
                pass
            server.response_buffer.pop(stream_id, None)
        server.system_metrics.record_request_end(model_name, resolved_version, status)


async def _ws_sender(websocket: WebSocket, buffer_item: ResponseBufferItem, stream_id: str) -> None:
    """Send output chunks from the response buffer to the WebSocket client."""
    try:
        while True:
            await buffer_item.event.wait()
            buffer_item.event.clear()

            while buffer_item.response_queue:
                response_data, status = buffer_item.response_queue.popleft()

                if status == LitAPIStatus.FINISH_STREAMING:
                    await websocket.close()
                    return

                if status == LitAPIStatus.ERROR:
                    error_msg = str(response_data)
                    if isinstance(response_data, Exception):
                        error_msg = str(response_data)
                    await websocket.send_json({"error": error_msg})
                    await websocket.close(code=1011)
                    return

                if isinstance(response_data, bytes):
                    await websocket.send_bytes(response_data)
                elif isinstance(response_data, str):
                    try:
                        parsed = json.loads(response_data)
                        await websocket.send_json(parsed)
                    except json.JSONDecodeError:
                        await websocket.send_text(response_data)
                else:
                    await websocket.send_json(response_data)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket sender error for stream {stream_id}: {e}")


async def _ws_receiver(
    websocket: WebSocket, server: LightServer, model_name: str, stream_id: str, version: str | None
) -> None:
    """Receive input chunks from the WebSocket client and forward to the worker."""
    try:
        while True:
            message = await websocket.receive_json()
            server.model_manager.infer_stream_chunk(
                model_name, stream_id, message, version=version, response_queue_id=0
            )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket receiver error for stream {stream_id}: {e}")


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

            if response_type == LoopResponseType.STREAMING and response_item.response_queue is not None:
                response_item.response_queue.append((response_data, status))
                response_item.event.set()
            else:
                response_item.response = (response_data, status)
                response_item.worker_id = int(worker_id)
                response_item.event.set()

        except asyncio.CancelledError:
            logger.debug("Response consumer cancelled")
            break
        except Exception as e:
            logger.error(f"Error in response consumer: {e}")
