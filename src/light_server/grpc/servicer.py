"""gRPC servicers for inference and model control."""

from __future__ import annotations

import json
import logging
from typing import Any

import grpc

from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

logger = logging.getLogger(__name__)


class InferenceServicer(litserve_pb2_grpc.InferenceServicer):
    """Handles inference requests via gRPC."""

    def __init__(self, server: Any) -> None:
        self._server = server

    def Predict(self, request: litserve_pb2.PredictRequest, context: grpc.ServicerContext) -> litserve_pb2.PredictResponse:
        model_name = request.model_name
        if not self._server.registry.is_ready(model_name):
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Model {model_name} not ready")
            return litserve_pb2.PredictResponse()

        try:
            payload = json.loads(request.payload.decode("utf-8"))
            uid = self._server.model_manager.infer(model_name, payload, transport=None)
            # TODO: wait for actual response from transport
            result = {"uid": uid, "model": model_name}
            return litserve_pb2.PredictResponse(
                payload=json.dumps(result).encode("utf-8")
            )
        except Exception as e:
            logger.exception(f"gRPC inference error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return litserve_pb2.PredictResponse()

    def StreamPredict(self, request: litserve_pb2.PredictRequest, context: grpc.ServicerContext):
        # TODO: implement streaming
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("StreamPredict not implemented")
        return


class ModelControlServicer(litserve_pb2_grpc.ModelControlServicer):
    """Handles model management requests via gRPC."""

    def __init__(self, server: Any) -> None:
        self._server = server

    def ModelReady(self, request: litserve_pb2.ModelReadyRequest, context: grpc.ServicerContext) -> litserve_pb2.ModelReadyResponse:
        ready = self._server.registry.is_ready(request.model_name)
        return litserve_pb2.ModelReadyResponse(ready=ready)

    def RepositoryIndex(self, request: litserve_pb2.Empty, context: grpc.ServicerContext) -> litserve_pb2.RepositoryIndexResponse:
        models = self._server.model_manager.list_repository()
        loaded = {m["name"]: m for m in self._server.registry.list_loaded()}
        response_models = []
        for m in models:
            state = loaded.get(m["name"], {}).get("status", "UNAVAILABLE")
            response_models.append(litserve_pb2.ModelInfo(
                name=m["name"],
                version=m["version"],
                state=state,
            ))
        return litserve_pb2.RepositoryIndexResponse(models=response_models)

    def LoadModel(self, request: litserve_pb2.LoadModelRequest, context: grpc.ServicerContext) -> litserve_pb2.StatusResponse:
        success = self._server.model_manager.load(request.model_name)
        if success:
            return litserve_pb2.StatusResponse(success=True, message=f"Model {request.model_name} loaded")
        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details(f"Failed to load model {request.model_name}")
        return litserve_pb2.StatusResponse(success=False, message="Failed")

    def UnloadModel(self, request: litserve_pb2.UnloadModelRequest, context: grpc.ServicerContext) -> litserve_pb2.StatusResponse:
        success = self._server.model_manager.unload(request.model_name)
        if success:
            return litserve_pb2.StatusResponse(success=True, message=f"Model {request.model_name} unloaded")
        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details(f"Failed to unload model {request.model_name}")
        return litserve_pb2.StatusResponse(success=False, message="Failed")
