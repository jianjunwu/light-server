"""Main LightServer controller integrating HTTP, gRPC, metrics, and model management."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import os
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
from light_server.core.response_buffer import TTLResponseBuffer
from light_server.observability import setup_multiproc_metrics, SystemMetrics
from litserve.transport.process_transport import MPQueueTransport
from litserve.utils import ResponseBufferItem

logger = logging.getLogger(__name__)


class LightServer:
    """Orchestrates HTTP, gRPC, metrics, and model lifecycle.

    This is the top-level controller that wires together all subsystems:
    - HTTP server (FastAPI + uvicorn, workers=1)
    - Optional gRPC server
    - Optional Prometheus metrics server
    - Model registry and model manager for load/unload/infer
    - Shared response buffer for async worker-to-handler communication

    Typical usage::

        from light_server import Config, LightServer

        config = Config()
        server = LightServer(config)
        server.run()   # blocks until SIGINT/SIGTERM

    Args:
        config: Server configuration including ports, model repository,
            logging, and gRPC/metrics settings.
    """

    def __init__(self, config: Config):
        self.config = config
        self.registry = ModelRegistry()

        # Shared transport using native multiprocessing.Queue (no Manager IPC)
        num_consumers = 1
        transport_queues = [mp.Queue() for _ in range(num_consumers)]
        self.transport = MPQueueTransport(None, transport_queues)

        # Metrics: setup prometheus multiprocess mode before any metric creation
        self._metrics_registry, self._metrics_dir = setup_multiproc_metrics()
        self.system_metrics = SystemMetrics(self._metrics_registry)

        self._log_queue: Any | None = None
        self._log_consumer: Any | None = None
        self._setup_logging()

        self.model_manager = ModelManager(
            repo_path=Path(config.model_repository.path),
            registry=self.registry,
            transport=self.transport,
            log_queue=self._log_queue,
            system_metrics=self.system_metrics,
        )

        self._shutdown_event = threading.Event()
        self._shutdown_lock = threading.Lock()
        buffer_ttl = self.config.server.timeout + 30.0
        self.response_buffer = TTLResponseBuffer(
            ttl_seconds=buffer_ttl,
            max_size=100_000,
        )
        self._response_task: asyncio.Task | None = None

        # Build HTTP app
        self.http_app = self._build_http_app()
        self._grpc_server: Any = None
        self._metrics_server: Any = None

    def _build_http_app(self) -> FastAPI:
        from light_server.http.app import create_app
        return create_app(self)

    def _setup_logging(self) -> None:
        log_cfg = self.config.logging
        if not log_cfg.info_output and not log_cfg.error_output:
            return

        self._log_queue = mp.Queue()

        from light_server.logging.consumer import LogConsumer
        from light_server.logging.queue_handler import MPQueueHandler

        self._log_consumer = LogConsumer(
            queue=self._log_queue,
            level=log_cfg.level,
            fmt=log_cfg.format,
            info_output=log_cfg.info_output,
            error_output=log_cfg.error_output,
            rotate_by=log_cfg.rotate_by,
            max_size=log_cfg.max_size,
            when=log_cfg.when,
            backup_count=log_cfg.backup_count,
        )
        self._log_consumer.start()

        # Main process also sends logs through the queue so everything lands in the same files
        root = logging.getLogger()
        root.setLevel(getattr(logging, log_cfg.level.upper(), logging.INFO))
        queue_handler = MPQueueHandler(self._log_queue)
        queue_handler.setLevel(getattr(logging, log_cfg.level.upper(), logging.INFO))
        root.addHandler(queue_handler)

    def run(self) -> None:
        """Start all services and block until shutdown.

        This method registers signal handlers, loads initial models,
        starts gRPC / metrics servers (if enabled), begins repository
        polling (if configured), and finally starts the HTTP server.
        It does not return until the process receives SIGINT or SIGTERM.
        """
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.response_buffer.start()

        self._load_initial_models()

        if self.config.grpc.enabled:
            self._start_grpc()

        if self.config.metrics.enabled:
            self._start_metrics()

        if self.config.model_repository.control_mode == "poll":
            self._start_poll_thread()

        try:
            self._start_http()
        finally:
            self.shutdown()

    def _load_initial_models(self) -> None:
        mode = self.config.model_repository.control_mode
        available = self.model_manager.list_repository()

        from collections import defaultdict
        by_model = defaultdict(list)
        for m in available:
            by_model[m["name"]].append(m)

        names_to_load = []
        if mode == "all":
            names_to_load = list(by_model.keys())
        elif mode in ("explicit", "poll"):
            names_to_load = self.config.load_models

        # Build lookup from config.models for per-model overrides
        config_override_by_name = {m.name: m for m in self.config.models if getattr(m, "name", None)}

        for name in names_to_load:
            model_cfg = self.model_manager.get_model_config(name)
            load_policy = model_cfg.get("load_policy", "explicit" if mode in ("explicit", "poll") else "all")
            versions_to_load = model_cfg.get("versions_to_load", [])
            default_version = model_cfg.get("default_version")

            models = by_model.get(name, [])
            versions_loaded = []

            override = config_override_by_name.get(name)

            for m in models:
                version = m["version"]
                if load_policy == "all":
                    should_load = True
                elif load_policy == "latest":
                    should_load = version == max(models, key=lambda x: x["version"])["version"]
                else:  # explicit
                    should_load = version in versions_to_load if versions_to_load else True

                if should_load:
                    self.model_manager.load(name, version, config_override=override)
                    versions_loaded.append(version)

            # Ensure default_version is active if specified and loaded
            if default_version and default_version in versions_loaded:
                if not self.registry.get_active_version(name):
                    self.registry.activate_version(name, default_version)

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
            log_config=None,
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
                registry=self._metrics_registry,
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
        available = {(m["name"], m["version"]) for m in self.model_manager.list_repository()}
        loaded = {(m["name"], m["version"]) for m in self.registry.list_loaded()}

        for name, version in available - loaded:
            model_cfg = self.model_manager.get_model_config(name)
            load_policy = model_cfg.get("load_policy", "explicit")
            versions_to_load = model_cfg.get("versions_to_load", [])

            should_load = False
            if load_policy == "all":
                should_load = True
            elif load_policy == "latest":
                # Only load if this is the latest version
                model_versions = [m["version"] for m in self.model_manager.list_repository() if m["name"] == name]
                should_load = version == max(model_versions)
            elif load_policy == "explicit":
                should_load = version in versions_to_load

            if should_load:
                logger.info(f"Poll: auto-loading {name} version {version}")
                self.model_manager.load(name, version)

        for name, version in loaded - available:
            logger.info(f"Poll: auto-unloading removed model {name} version {version}")
            self.model_manager.unload(name, version)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        logger.info(f"Received signal {signum}, shutting down...")
        self._shutdown_event.set()
        self.shutdown()
        sys.exit(0)

    def shutdown(self) -> None:
        """Gracefully shut down all services.

        Stops the response buffer, unloads all models (terminating workers),
        shuts down gRPC / metrics / logging servers, and cleans up temporary
        Prometheus multiproc directories. This is called automatically on
        SIGINT/SIGTERM, or can be invoked programmatically.
        """
        with self._shutdown_lock:
            if getattr(self, "_shutdown_done", False):
                return
            self._shutdown_done = True

        logger.info("Shutting down LightServer...")
        self.response_buffer.stop()
        # Unload all loaded models by iterating through the registry
        for entry in self.registry.list_loaded():
            self.model_manager.unload(entry["name"], entry["version"])

        # Close transport queues to unblock the response consumer
        try:
            self.transport._closed = True
        except Exception:
            pass
        for q in getattr(self.transport, "_queues", []):
            try:
                q.close()
                q.join_thread()
            except Exception:
                pass

        # Wait for all worker processes to fully exit (join even if not alive to reap zombies)
        for workers in list(self.model_manager._workers.values()):
            for worker in workers:
                try:
                    if worker.is_alive():
                        worker.terminate()
                    worker.join(timeout=3)
                    if worker.is_alive():
                        worker.kill()
                        worker.join(timeout=2)
                except Exception:
                    pass

        # Release shared memory buffers and manager process
        self.model_manager.shutdown()

        if self._grpc_server:
            self._grpc_server.stop(5)
        if self._metrics_server:
            self._metrics_server.shutdown()
        if self._log_consumer:
            self._log_consumer.stop()
        # Clean up prometheus multiprocess temp directory
        if self._metrics_dir and os.path.isdir(self._metrics_dir):
            import shutil
            try:
                shutil.rmtree(self._metrics_dir)
            except OSError as e:
                logger.warning(f"Failed to clean up metrics dir {self._metrics_dir}: {e}")
        logger.info("Shutdown complete")
