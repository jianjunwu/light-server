"""HTTP inference handlers with async transport response handling."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from light_server.core.ensemble import EnsembleExecutor
from light_server.core.exceptions import (
    InferenceTimeoutError,
    LightServerError,
    ModelNotReadyError,
    QueueFullError,
    WorkerCrashedError,
)
from light_server.core.model_manager import (
    submit_infer,
    submit_stream_cancel,
    submit_stream_chunk,
    submit_stream_close,
    submit_stream_open,
)
from light_server.core.response import error_dict
from light_server.core.validation import validate_model_name, validate_version
from light_server.http.state import HTTPState
from litserve.utils import LitAPIStatus, LoopResponseType, ResponseBufferItem

logger = logging.getLogger(__name__)


def create_inference_routes(app: FastAPI, state: HTTPState) -> None:
    """Register inference routes on the FastAPI app."""

    @app.on_event("startup")
    async def start_response_consumer() -> None:
        """Start background task to consume responses from transport."""
        asyncio.create_task(_response_consumer(state))

    @app.post("/v2/models/{model_name}/infer")
    async def infer(model_name: str, request: Request) -> JSONResponse:
        """Inference against the active version of a model."""
        return await _do_infer(state, model_name, None, request)

    @app.post("/v2/models/{model_name}/versions/{version}/infer")
    async def infer_version(model_name: str, version: str, request: Request) -> JSONResponse:
        """Inference against a specific version of a model."""
        return await _do_infer(state, model_name, version, request)

    @app.websocket("/v2/models/{model_name}/stream")
    async def ws_stream(model_name: str, websocket: WebSocket) -> None:
        await _do_ws_stream(state, model_name, None, websocket)

    @app.websocket("/v2/models/{model_name}/versions/{version}/stream")
    async def ws_stream_version(model_name: str, version: str, websocket: WebSocket) -> None:
        await _do_ws_stream(state, model_name, version, websocket)


async def _do_infer(state: HTTPState, model_name: str, version: str | None, request: Request) -> JSONResponse:
    validate_model_name(model_name)
    if version is not None:
        validate_version(version)

    resolved_version = version or state.registry.get_active_version(model_name) or "unknown"
    state.system_metrics.record_request_start(model_name, resolved_version)

    status = "2xx"
    try:
        if not state.registry.is_ready(model_name, version):
            status = "4xx"
            detail = f"Model {model_name}"
            if version:
                detail += f" version {version}"
            detail += " not ready"
            raise ModelNotReadyError(detail)

        payload = await request.json()

        # Build request metadata for model hooks
        request_meta = {
            "headers": dict(request.headers),
            "query_params": dict(request.query_params),
            "client_host": request.client.host if request.client else None,
            "method": request.method,
            "url": str(request.url),
            "path_params": {"model_name": model_name, "version": version},
        }

        # Call model-level on_request hook if available
        lit_api = state.get_litapi_hooks(model_name, resolved_version)
        if lit_api is not None and hasattr(lit_api, "on_request"):
            payload = lit_api.on_request(payload, request_meta)

        entry = state.registry.get(model_name, version)
        if entry is not None and entry.get("model_type") == "ensemble":
            result = await _do_ensemble_infer(state, model_name, version, payload)
        else:
            result = await _do_litapi_infer(state, model_name, version, payload, request_meta)

        return result

    except LightServerError as e:
        status = "5xx" if e.status_code >= 500 else "4xx"
        raise
    except asyncio.TimeoutError:
        status = "timeout"
        raise
    except Exception:
        status = "5xx"
        raise
    finally:
        state.system_metrics.record_request_end(model_name, resolved_version, status)


async def _do_ensemble_infer(
    state: HTTPState, model_name: str, version: str | None, payload: dict[str, Any]
) -> JSONResponse:
    """Execute an ensemble DAG and return the final step's output."""
    entry = state.registry.get(model_name, version)
    if entry is None:
        raise ModelNotReadyError(f"Model {model_name} not found")

    ensemble_config = entry.get("ensemble_config")
    if ensemble_config is None:
        raise WorkerCrashedError("Ensemble config missing")

    try:
        executor = EnsembleExecutor()
        result = await executor.execute(state, ensemble_config, payload, ensemble_name=model_name)
        return JSONResponse(result)
    except LightServerError:
        raise
    except Exception as e:
        logger.exception(f"Ensemble inference error for {model_name}: {e}")
        raise WorkerCrashedError(str(e)) from e


async def _do_litapi_infer(
    state: HTTPState,
    model_name: str,
    version: str | None,
    payload: dict[str, Any],
    request_meta: dict[str, Any] | None = None,
) -> JSONResponse:
    """Submit inference to a LitAPI worker and await response."""
    uid = None
    try:
        uid = submit_infer(
            state.registry,
            state.shm_buffer,
            state.system_metrics,
            model_name,
            payload,
            version=version,
            response_queue_id=state.response_queue_id,
        )

        event = asyncio.Event()
        state.response_buffer[uid] = ResponseBufferItem(event=event)

        await asyncio.wait_for(
            event.wait(), timeout=state.config.server.timeout
        )

        response_item = state.response_buffer.pop(uid)
        response_data, status = response_item.response

        # Call model-level on_response hook if available
        lit_api = state.get_litapi_hooks(model_name, version)
        if lit_api is not None and hasattr(lit_api, "on_response"):
            response_meta = {
                "model_name": model_name,
                "version": version,
                "request_meta": request_meta or {},
                "status": "error" if status == LitAPIStatus.ERROR else "ok",
            }
            try:
                response_data = lit_api.on_response(response_data, response_meta)
            except Exception as e:
                logger.warning(f"on_response failed for {model_name}: {e}")

        if status == LitAPIStatus.ERROR:
            raise WorkerCrashedError("Inference error")

        return JSONResponse(response_data)

    except QueueFullError:
        raise
    except asyncio.TimeoutError:
        state.response_buffer.pop(uid, None)
        raise InferenceTimeoutError("Inference timeout")
    except asyncio.CancelledError:
        state.response_buffer.pop(uid, None)
        raise
    except LightServerError:
        raise
    except Exception as e:
        logger.exception(f"Inference error for {model_name}: {e}")
        raise WorkerCrashedError(str(e)) from e
    finally:
        if uid is not None:
            resolved_version = version or state.registry.get_active_version(model_name) or "unknown"
            state.system_metrics.dec_queue_depth(model_name, resolved_version)


async def _do_ws_stream(
    state: HTTPState, model_name: str, version: str | None, websocket: WebSocket
) -> None:
    """Handle a bidirectional WebSocket stream."""
    try:
        validate_model_name(model_name)
        if version is not None:
            validate_version(version)
    except LightServerError as exc:
        await websocket.close(code=1011, reason=str(exc))
        return

    await websocket.accept()

    resolved_version = version or state.registry.get_active_version(model_name) or "unknown"
    state.system_metrics.record_request_start(model_name, resolved_version)

    stream_id: str | None = None
    status = "2xx"
    try:
        if not state.registry.is_ready(model_name, version):
            status = "4xx"
            await websocket.close(code=1011, reason=f"Model {model_name} not ready")
            return

        stream_id = f"ws-{uuid.uuid4().hex}"

        event = asyncio.Event()
        buffer_item = ResponseBufferItem(event=event, response_queue=deque())
        state.response_buffer[stream_id] = buffer_item

        try:
            submit_stream_open(
                state.registry,
                state._stream_routing,
                state._stream_lock,
                state._worker_loads,
                model_name,
                stream_id,
                version=version,
                response_queue_id=state.response_queue_id,
            )
        except QueueFullError as exc:
            state.response_buffer.pop(stream_id, None)
            await websocket.close(code=1011, reason=str(exc))
            return
        state.system_metrics.record_stream_open(model_name, resolved_version, "websocket", stream_id)

        sender_task = asyncio.create_task(
            _ws_sender(websocket, buffer_item, stream_id, state, model_name, resolved_version),
            name=f"ws-sender-{stream_id}",
        )
        receiver_task = asyncio.create_task(
            _ws_receiver(websocket, state, model_name, stream_id, version),
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
            state.system_metrics.record_stream_close(model_name, resolved_version, "websocket", stream_id)
            try:
                submit_stream_close(
                    state.registry,
                    state._stream_routing,
                    state._worker_loads,
                    model_name,
                    stream_id,
                    version=version,
                    response_queue_id=state.response_queue_id,
                )
            except Exception:
                pass
            state.response_buffer.pop(stream_id, None)
        state.system_metrics.record_request_end(model_name, resolved_version, status)


async def _ws_sender(
    websocket: WebSocket,
    buffer_item: ResponseBufferItem,
    stream_id: str,
    state: HTTPState,
    model_name: str,
    version: str,
) -> None:
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
                    await websocket.send_json(error_dict("INFERENCE_ERROR", error_msg))
                    await websocket.close(code=1011)
                    return

                state.system_metrics.record_stream_chunk(model_name, version, "websocket", stream_id)

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
    websocket: WebSocket, state: HTTPState, model_name: str, stream_id: str, version: str | None
) -> None:
    """Receive input chunks from the WebSocket client and forward to the worker."""
    try:
        while True:
            message = await websocket.receive_json()
            submit_stream_chunk(
                state.registry,
                state._stream_routing,
                model_name,
                stream_id,
                message,
                version=version,
                response_queue_id=state.response_queue_id,
            )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WebSocket receiver error for stream {stream_id}: {e}")


async def _response_consumer(state: HTTPState) -> None:
    """Continuously read responses from transport and signal waiting handlers."""
    transport = state.transport
    consumer_id = state.response_queue_id
    while True:
        try:
            result = await transport.areceive(consumer_id=consumer_id)
            if result is None:
                continue

            # Format: (uid, (response_data, status, response_type, worker_id))
            uid, (response_data, status, response_type, worker_id) = result

            response_item = state.response_buffer.get(uid)
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
