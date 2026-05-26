"""Per-process HTTP state for multi-process and single-process modes."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from light_server.config import Config
from light_server.core.registry import ModelRegistry
from litserve.transport.process_transport import MPQueueTransport

logger = logging.getLogger(__name__)


class HTTPState:
    """Lightweight state shared with HTTP worker processes.

    The picklable subset (registry, transport, config, queues) is passed
    to spawn-context workers.  Non-picklable fields (metrics, buffers,
    hook cache) are recreated in each worker via :meth:`init_worker_locals`.

    For single-process mode ``_model_manager`` can be set directly so
    that load/unload calls bypass IPC.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        transport: MPQueueTransport,
        config: Config,
        response_queue_id: int = 0,
        repo_path: Path | None = None,
        log_queue: Any | None = None,
        admin_queue: Any | None = None,
        admin_response_queue: Any | None = None,
        metrics_dir: str | None = None,
        model_manager: Any | None = None,
        response_buffer: Any | None = None,
        config_path: str | None = None,
    ) -> None:
        self.registry = registry
        self.transport = transport
        self.config = config
        self.response_queue_id = response_queue_id
        self.repo_path = repo_path or Path(".")
        self.log_queue = log_queue
        self.admin_queue = admin_queue
        self.admin_response_queue = admin_response_queue
        self.metrics_dir = metrics_dir
        self._model_manager = model_manager
        self._config_path = config_path

        # Per-process locals (not pickled)
        self._system_metrics: Any | None = None
        self._shm_buffer: Any | None = None
        self._hook_cache: dict[str, Any] = {}
        self._response_buffer: Any = response_buffer if response_buffer is not None else {}
        self._stream_routing: dict[str, int] = {}
        self._stream_lock = threading.Lock()
        self._worker_loads: dict[str, dict[int, int]] = {}

    # ------------------------------------------------------------------
    # Pickle support
    # ------------------------------------------------------------------

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        # Drop non-picklable / per-process state
        state.pop("_system_metrics", None)
        state.pop("_shm_buffer", None)
        state.pop("_hook_cache", None)
        state.pop("_response_buffer", None)
        state.pop("_model_manager", None)
        state.pop("_stream_lock", None)
        state.pop("_stream_routing", None)
        state.pop("_worker_loads", None)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._system_metrics = None
        self._shm_buffer = None
        self._hook_cache = {}
        self._response_buffer = {}  # workers create their own
        self._model_manager = None
        self._stream_routing = {}
        self._stream_lock = threading.Lock()
        self._worker_loads = {}

    # ------------------------------------------------------------------
    # Per-process initialisation (call inside worker)
    # ------------------------------------------------------------------

    def init_worker_locals(self) -> None:
        """Create process-local resources (metrics, SHM buffer)."""
        from light_server.core.shm_buffer import ShmPayloadBuffer
        from light_server.observability import setup_multiproc_metrics, SystemMetrics

        if self.metrics_dir:
            os.environ["PROMETHEUS_MULTIPROC_DIR"] = self.metrics_dir

        registry, _, _ = setup_multiproc_metrics(clean=False)
        self._system_metrics = SystemMetrics(registry)
        self._shm_buffer = ShmPayloadBuffer()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def system_metrics(self) -> Any:
        if self._system_metrics is None:
            self.init_worker_locals()
        return self._system_metrics

    @property
    def shm_buffer(self) -> Any:
        if self._shm_buffer is None:
            self.init_worker_locals()
        return self._shm_buffer

    @property
    def response_buffer(self) -> dict[str, Any]:
        return self._response_buffer

    # ------------------------------------------------------------------
    # Hook cache
    # ------------------------------------------------------------------

    def get_litapi_hooks(self, name: str, version: str | None) -> Any | None:
        """Load a LitAPI instance for hooks (on_request / on_response / health_check).

        Instances are cached per process.  Only models that define at least
        one hook method are kept in memory.
        """
        if version is None:
            version = self.registry.get_active_version(name)
        if version is None:
            return None

        key = f"{name}_{version}"
        if key in self._hook_cache:
            # If model was unloaded, invalidate stale cache entry
            if self.registry.get(name, version) is None:
                self._hook_cache.pop(key, None)
                return None

        if key not in self._hook_cache:
            entry = self.registry.get(name, version)
            if entry is None:
                self._hook_cache[key] = None
                return None

            model_dir = entry.get("model_dir")
            if not model_dir:
                self._hook_cache[key] = None
                return None

            model_py = Path(model_dir) / "model.py"
            if not model_py.exists():
                self._hook_cache[key] = None
                return None

            try:
                from light_server.core.loader import load_litapi_from_file
                LitAPIClass = load_litapi_from_file(model_py, suppress_prometheus=True)
                cfg = entry.get("config", {})
                lit_api = LitAPIClass(
                    max_batch_size=cfg.get("max_batch_size", 1),
                    batch_timeout=cfg.get("batch_timeout", 0.0),
                    api_path=cfg.get("api_path", "/predict"),
                    stream=cfg.get("stream", False),
                )
                lit_api.config = cfg
                lit_api.pre_setup()
                if (
                    hasattr(lit_api, "on_request")
                    or hasattr(lit_api, "on_response")
                    or hasattr(lit_api, "health_check")
                ):
                    self._hook_cache[key] = lit_api
                else:
                    self._hook_cache[key] = None
            except Exception as exc:
                logger.warning(f"Failed to load hooks for {name} v{version}: {exc}")
                self._hook_cache[key] = None

        return self._hook_cache[key]

    # ------------------------------------------------------------------
    # Repository scan (local filesystem)
    # ------------------------------------------------------------------

    def load_dynamic_endpoints(self) -> dict[str, dict[str, Any]]:
        """Scan the model repository for custom endpoint definitions."""
        if self._model_manager is not None:
            return self._model_manager.load_dynamic_endpoints()
        from light_server.core.model_manager import ModelManager

        mgr = ModelManager(repo_path=self.repo_path, registry=self.registry)
        return mgr.load_dynamic_endpoints()

    def list_repository(self) -> list[dict[str, Any]]:
        """Scan the model repository for available models."""
        if self._model_manager is not None:
            return self._model_manager.list_repository()
        from light_server.core.model_manager import ModelManager

        mgr = ModelManager(repo_path=self.repo_path, registry=self.registry)
        return mgr.list_repository()

    # ------------------------------------------------------------------
    # Admin IPC (load / unload)
    # ------------------------------------------------------------------

    async def load_model(self, name: str, version: str) -> bool:
        """Load a model version (direct or via IPC)."""
        if self._model_manager is not None:
            return self._model_manager.load(name, version)
        result = await self._admin_call("load", name=name, version=version)
        return result.get("success", False)

    async def unload_model(self, name: str, version: str | None) -> bool:
        """Unload a model (direct or via IPC)."""
        if self._model_manager is not None:
            return self._model_manager.unload(name, version)
        result = await self._admin_call("unload", name=name, version=version)
        return result.get("success", False)

    async def activate_model(self, name: str, version: str) -> bool:
        """Activate a model version (local registry operation)."""
        if self._model_manager is not None:
            return self._model_manager.activate(name, version)
        return self.registry.activate_version(name, version)

    async def _admin_call(self, cmd: str, **kwargs: Any) -> dict[str, Any]:
        """Send a command to the main process via the admin queue."""
        if self.admin_queue is None or self.admin_response_queue is None:
            raise RuntimeError("Admin IPC not available in this process")

        request_id = uuid.uuid4().hex
        self.admin_queue.put(
            {
                "cmd": cmd,
                "request_id": request_id,
                "response_queue": self.admin_response_queue,
                **kwargs,
            }
        )

        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, self.admin_response_queue.get),
            timeout=60.0,
        )
        return result
