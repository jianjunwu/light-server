"""gRPC servicers for inference and model control."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import grpc

from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc
from litserve.utils import LitAPIStatus

logger = logging.getLogger(__name__)


@dataclass
class _SyncBufferItem:
    """Thread-safe response buffer for gRPC synchronous servicer threads."""

    event: threading.Event = field(default_factory=threading.Event)
    response_queue: deque = field(default_factory=deque)
    response: Any | None = None
    worker_id: int | None = None


def _encode_payload(data: Any) -> bytes:
    """Encode response data to bytes for gRPC payload."""
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    return json.dumps(data).encode("utf-8")


class InferenceServicer(litserve_pb2_grpc.InferenceServicer):
    """Handles inference requests via gRPC."""

    def __init__(self, server: Any) -> None:
        self._server = server

    def Predict(self, request: litserve_pb2.PredictRequest, context: grpc.ServicerContext) -> litserve_pb2.PredictResponse:
        model_name = request.model_name
        version = request.version or None
        if version == "":
            version = None

        if not self._server.registry.is_ready(model_name, version):
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Model {model_name} not ready")
            return litserve_pb2.PredictResponse()

        try:
            payload = json.loads(request.payload.decode("utf-8"))
            uid = self._server.model_manager.infer(
                model_name, payload, version=version, response_queue_id=0
            )

            buffer_item = _SyncBufferItem()
            self._server.response_buffer[uid] = buffer_item

            if not buffer_item.event.wait(timeout=self._server.config.server.timeout):
                self._server.response_buffer.pop(uid, None)
                context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
                return litserve_pb2.PredictResponse()

            response_item = self._server.response_buffer.pop(uid)
            response_data, status = response_item.response

            if status == LitAPIStatus.ERROR:
                context.set_code(grpc.StatusCode.INTERNAL)
                return litserve_pb2.PredictResponse()

            return litserve_pb2.PredictResponse(payload=_encode_payload(response_data))

        except json.JSONDecodeError as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"Invalid JSON payload: {e}")
            return litserve_pb2.PredictResponse()
        except Exception as e:
            logger.exception(f"gRPC Predict error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            return litserve_pb2.PredictResponse()

    def StreamPredict(self, request: litserve_pb2.PredictRequest, context: grpc.ServicerContext):
        model_name = request.model_name
        version = request.version or None
        if version == "":
            version = None

        if not self._server.registry.is_ready(model_name, version):
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Model {model_name} not ready")
            return

        stream_id = f"grpc-sp-{uuid.uuid4().hex}"
        buffer_item = _SyncBufferItem(response_queue=deque())
        self._server.response_buffer[stream_id] = buffer_item

        try:
            payload = json.loads(request.payload.decode("utf-8"))
            self._server.model_manager.infer_stream_open(
                model_name, stream_id, version=version, response_queue_id=0
            )
            self._server.system_metrics.record_stream_open(model_name, version or "1", "grpc", stream_id)
            self._server.model_manager.infer_stream_chunk(
                model_name, stream_id, payload, version=version, response_queue_id=0
            )
            self._server.model_manager.infer_stream_close(
                model_name, stream_id, version=version
            )

            while True:
                if not buffer_item.event.wait(timeout=self._server.config.server.timeout):
                    break
                buffer_item.event.clear()

                while buffer_item.response_queue:
                    response_data, status = buffer_item.response_queue.popleft()

                    if status == LitAPIStatus.FINISH_STREAMING:
                        return
                    if status == LitAPIStatus.ERROR:
                        context.set_code(grpc.StatusCode.INTERNAL)
                        return

                    self._server.system_metrics.record_stream_chunk(model_name, version or "1", "grpc", stream_id)
                    yield litserve_pb2.PredictResponse(payload=_encode_payload(response_data))

        except json.JSONDecodeError as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"Invalid JSON payload: {e}")
        except Exception as e:
            logger.exception(f"gRPC StreamPredict error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
        finally:
            self._server.response_buffer.pop(stream_id, None)
            self._server.system_metrics.record_stream_close(
                model_name, version or "1", "grpc", stream_id
            )
            try:
                self._server.model_manager.infer_stream_close(
                    model_name, stream_id, version=version
                )
            except Exception:
                pass

    def BidirectionalStream(self, request_iterator, context: grpc.ServicerContext):
        stream_id = f"grpc-bs-{uuid.uuid4().hex}"
        model_name: str | None = None
        version: str | None = None

        buffer_item = _SyncBufferItem(response_queue=deque())
        self._server.response_buffer[stream_id] = buffer_item

        # Consume request_iterator in a background thread so we can interleave reads and writes
        input_queue: queue.Queue = queue.Queue()
        reader_done = threading.Event()

        def reader() -> None:
            try:
                for chunk in request_iterator:
                    input_queue.put(chunk)
            except Exception:
                pass
            finally:
                input_queue.put(None)
                reader_done.set()

        threading.Thread(target=reader, daemon=True).start()

        try:
            while True:
                # Process any available input chunks
                try:
                    chunk = input_queue.get(timeout=0.01)
                except queue.Empty:
                    chunk = None

                if chunk is not None:
                    if model_name is None:
                        meta = json.loads(chunk.payload.decode("utf-8"))
                        model_name = meta.get("model_name")
                        version = meta.get("version") or None

                        if not model_name:
                            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                            context.set_details("model_name is required in first chunk")
                            return

                        if not self._server.registry.is_ready(model_name, version):
                            context.set_code(grpc.StatusCode.NOT_FOUND)
                            context.set_details(f"Model {model_name} not ready")
                            return

                        self._server.model_manager.infer_stream_open(
                            model_name, stream_id, version=version, response_queue_id=0
                        )
                        self._server.system_metrics.record_stream_open(
                            model_name, version or "1", "grpc", stream_id
                        )
                        continue

                    payload = json.loads(chunk.payload.decode("utf-8"))
                    if chunk.is_final:
                        self._server.model_manager.infer_stream_close(
                            model_name, stream_id, version=version
                        )
                    else:
                        self._server.model_manager.infer_stream_chunk(
                            model_name, stream_id, payload, version=version, response_queue_id=0
                        )

                # Yield any available responses
                if buffer_item.event.wait(timeout=0.01):
                    buffer_item.event.clear()
                    while buffer_item.response_queue:
                        response_data, status = buffer_item.response_queue.popleft()
                        if status == LitAPIStatus.FINISH_STREAMING:
                            yield litserve_pb2.StreamChunk(
                                stream_id=stream_id, payload=b"", is_final=True
                            )
                            return
                        if status == LitAPIStatus.ERROR:
                            context.set_code(grpc.StatusCode.INTERNAL)
                            return
                        self._server.system_metrics.record_stream_chunk(
                            model_name, version or "1", "grpc", stream_id
                        )
                        yield litserve_pb2.StreamChunk(
                            stream_id=stream_id,
                            payload=_encode_payload(response_data),
                            is_final=False,
                        )

                # Exit when reader is done and no more pending input
                if reader_done.is_set() and input_queue.empty():
                    # Wait a bit more for final responses
                    if buffer_item.event.wait(timeout=1.0):
                        buffer_item.event.clear()
                        while buffer_item.response_queue:
                            response_data, status = buffer_item.response_queue.popleft()
                            if status == LitAPIStatus.FINISH_STREAMING:
                                yield litserve_pb2.StreamChunk(
                                    stream_id=stream_id, payload=b"", is_final=True
                                )
                                return
                            if status == LitAPIStatus.ERROR:
                                context.set_code(grpc.StatusCode.INTERNAL)
                                return
                            self._server.system_metrics.record_stream_chunk(
                                model_name, version or "1", "grpc", stream_id
                            )
                            yield litserve_pb2.StreamChunk(
                                stream_id=stream_id,
                                payload=_encode_payload(response_data),
                                is_final=False,
                            )
                    break

        except json.JSONDecodeError as e:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"Invalid JSON payload: {e}")
        except Exception as e:
            logger.exception(f"gRPC BidirectionalStream error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
        finally:
            self._server.response_buffer.pop(stream_id, None)
            if model_name:
                self._server.system_metrics.record_stream_close(
                    model_name, version or "1", "grpc", stream_id
                )
                try:
                    self._server.model_manager.infer_stream_close(
                        model_name, stream_id, version=version
                    )
                except Exception:
                    pass


class ModelControlServicer(litserve_pb2_grpc.ModelControlServicer):
    """Handles model management requests via gRPC."""

    def __init__(self, server: Any) -> None:
        self._server = server

    def ModelReady(self, request: litserve_pb2.ModelReadyRequest, context: grpc.ServicerContext) -> litserve_pb2.ModelReadyResponse:
        version = request.version or None
        if version == "":
            version = None
        ready = self._server.registry.is_ready(request.model_name, version)
        return litserve_pb2.ModelReadyResponse(ready=ready)

    def RepositoryIndex(self, request: litserve_pb2.Empty, context: grpc.ServicerContext) -> litserve_pb2.RepositoryIndexResponse:
        models = self._server.model_manager.list_repository()
        loaded = {m["name"]: m for m in self._server.registry.list_loaded()}
        response_models = []
        for m in models:
            state = loaded.get(m["name"], {}).get("status", "UNAVAILABLE")
            response_models.append(
                litserve_pb2.ModelInfo(
                    name=m["name"],
                    version=m["version"],
                    state=state,
                )
            )
        return litserve_pb2.RepositoryIndexResponse(models=response_models)

    def LoadModel(self, request: litserve_pb2.LoadModelRequest, context: grpc.ServicerContext) -> litserve_pb2.StatusResponse:
        version = request.version or "1"
        success = self._server.model_manager.load(request.model_name, version=version)
        if success:
            return litserve_pb2.StatusResponse(
                success=True, message=f"Model {request.model_name} v{version} loaded"
            )
        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details(f"Failed to load model {request.model_name} v{version}")
        return litserve_pb2.StatusResponse(success=False, message="Failed")

    def UnloadModel(self, request: litserve_pb2.UnloadModelRequest, context: grpc.ServicerContext) -> litserve_pb2.StatusResponse:
        version = request.version or None
        if version == "":
            version = None
        success = self._server.model_manager.unload(request.model_name, version=version)
        if success:
            msg = f"Model {request.model_name}"
            if version:
                msg += f" v{version}"
            msg += " unloaded"
            return litserve_pb2.StatusResponse(success=True, message=msg)
        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details(f"Failed to unload model {request.model_name}")
        return litserve_pb2.StatusResponse(success=False, message="Failed")
