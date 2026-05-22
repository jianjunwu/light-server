"""Main LightServer controller integrating HTTP, gRPC, metrics, and model management."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

from light_server.config import Config, ModelConfig
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry
from litserve.transport.factory import TransportConfig, create_transport_from_config
from litserve.utils import ResponseBufferItem

logger = logging.getLogger(__name__)


class LightServer:
    """Orchestrates HTTP, gRPC, metrics, and model lifecycle."""

    def __init__(self, config: Config):
        self.config = config
        self.manager = mp.Manager()
        self.registry = ModelRegistry(self.manager)

        # Shared transport for all models
        transport_config = TransportConfig(
            transport_type="mp",
            num_consumers=1,
        )
        transport_config.manager = self.manager
        self.transport = create_transport_from_config(transport_config)

        self.model_manager = ModelManager(
            repo_path=Path(config.model_repository.path),
            registry=self.registry,
            transport=self.transport,
        )

        self._shutdown_event = threading.Event()
        self.response_buffer: dict[str, ResponseBufferItem] = {}
        self._response_task: asyncio.Task | None = None

        # Build HTTP app
        self.http_app = self._build_http_app()
        self._grpc_server: Any = None
        self._metrics_server: Any = None

    def _build_http_app(self) -> FastAPI:
        from light_server.http.app import create_app
        return create_app(self)

    def run(self) -> None:
        """Start all services."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._load_initial_models()

        if self.config.grpc.enabled:
            self._start_grpc()

        if self.config.metrics.enabled:
            self._start_metrics()

        if self.config.model_repository.control_mode == "poll":
            self._start_poll_thread()

        self._start_http()

    def _load_initial_models(self) -> None:
        mode = self.config.model_repository.control_mode

        if mode == "none":
            available = self.model_manager.list_repository()
            for model_info in available:
                self.model_manager.load(model_info["name"], model_info["version"])

        elif mode in ("explicit", "poll"):
            for name in self.config.load_models:
                available = self.model_manager.list_repository()
                for m in available:
                    if m["name"] == name:
                        self.model_manager.load(name, m["version"])
                        break

    def _start_http(self) -> None:
        host = self.config.server.host
        port = self.config.server.http_port
        log_level = self.config.server.log_level

        uvconfig = uvicorn.Config(
            app=self.http_app,
            host=host,
            port=port,
            log_level=log_level,
            workers=1,
        )
        server = uvicorn.Server(uvconfig)

        logger.info(f"Starting HTTP server on {host}:{port}")
        try:
            server.run()
        except Exception as e:
            logger.exception(f"HTTP server error: {e}")

    def _start_grpc(self) -> None:
        try:
            from light_server.grpc.server import start_grpc_server
            self._grpc_server = start_grpc_server(
                self,
                host=self.config.server.host,
                port=self.config.server.grpc_port,
                max_workers=self.config.grpc.max_workers,
            )
            logger.info(f"Started gRPC server on {self.config.server.host}:{self.config.server.grpc_port}")
        except Exception as e:
            logger.exception(f"Failed to start gRPC server: {e}")

    def _start_metrics(self) -> None:
        try:
            from light_server.metrics.exporter import start_metrics_server
            self._metrics_server = start_metrics_server(
                host=self.config.server.host,
                port=self.config.server.metrics_port,
            )
            logger.info(f"Started metrics server on {self.config.server.host}:{self.config.server.metrics_port}")
        except Exception as e:
            logger.exception(f"Failed to start metrics server: {e}")

    def _start_poll_thread(self) -> None:
        def poll():
            interval = self.config.model_repository.poll_interval
            while not self._shutdown_event.is_set():
                time.sleep(interval)
                self._poll_repository()

        t = threading.Thread(target=poll, daemon=True, name="repo-poll")
        t.start()
        logger.info(f"Started repository polling (interval={self.config.model_repository.poll_interval}s)")

    def _poll_repository(self) -> None:
        available = {m["name"] for m in self.model_manager.list_repository()}
        loaded = {m["name"] for m in self.registry.list_loaded()}

        for name in available - loaded:
            logger.info(f"Poll: auto-loading new model {name}")
            self.model_manager.load(name)

        for name in loaded - available:
            logger.info(f"Poll: auto-unloading removed model {name}")
            self.model_manager.unload(name)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        logger.info(f"Received signal {signum}, shutting down...")
        self._shutdown_event.set()
        self.shutdown()
        sys.exit(0)

    def shutdown(self) -> None:
        logger.info("Shutting down LightServer...")
        for name in list(self._workers.keys()) if hasattr(self, '_workers') else []:
            self.model_manager.unload(name)
        if self._grpc_server:
            self._grpc_server.stop(5)
        if self._metrics_server:
            self._metrics_server.shutdown()
        self.manager.shutdown()
        logger.info("Shutdown complete")
