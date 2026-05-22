"""gRPC server starter."""

from __future__ import annotations

import logging
from concurrent import futures
from typing import Any

import grpc

from light_server.grpc.proto import litserve_pb2_grpc
from light_server.grpc.servicer import InferenceServicer, ModelControlServicer

logger = logging.getLogger(__name__)


def start_grpc_server(server: Any, host: str = "0.0.0.0", port: int = 8001, max_workers: int = 10) -> grpc.Server:
    """Start the gRPC server in a background thread."""
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))

    litserve_pb2_grpc.add_InferenceServicer_to_server(InferenceServicer(server), grpc_server)
    litserve_pb2_grpc.add_ModelControlServicer_to_server(ModelControlServicer(server), grpc_server)

    grpc_server.add_insecure_port(f"{host}:{port}")
    grpc_server.start()
    return grpc_server
