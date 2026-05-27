"""Model lifecycle manager: load, unload, inference."""

from __future__ import annotations

import fnmatch
import itertools
import logging
import multiprocessing as mp
import os
import queue
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from light_server.config import ModelConfig
from light_server.core.ensemble import EnsembleParser
from light_server.core.loader import load_litapi_from_file, load_module_from_file
from light_server.core.registry import ModelRegistry
from light_server.core.shm_buffer import ShmPayloadBuffer
from light_server.core.validation import validate_model_name, validate_version
from litserve import LitAPI

logger = logging.getLogger(__name__)


from light_server.core.exceptions import (
    InferenceTimeoutError,
    ModelNotFoundError,
    ModelNotReadyError,
    QueueFullError,
    ValidationError,
    WorkerCrashedError,
)


class ModelManager:
    """Manages loading/unloading of models and their inference workers.

    Each model version gets its own set of worker processes.  The manager
    coordinates with :class:`ModelRegistry` to track state, and with
    :class:`SystemMetrics` to emit load/unload metrics.

    Key responsibilities:
    - Scan the model repository (plain dirs + ``.lma`` artifacts)
    - Load/unload model versions with multiprocessing workers
    - Route inference requests to worker queues
    - Manage bidirectional stream routing and worker load balancing
    """

    def __init__(
        self,
        repo_path: Path,
        registry: ModelRegistry,
        transport: Any | None = None,
        callback_runner: Any | None = None,
        log_queue: Any | None = None,
        system_metrics: Any | None = None,
        manager: Any | None = None,
    ):
        self.repo_path = Path(repo_path)
        self.registry = registry
        self.transport = transport
        self.callback_runner = callback_runner
        self.log_queue = log_queue
        self.system_metrics = system_metrics
        self._manager = manager or mp.Manager()
        self._mp_ctx = mp.get_context("spawn")
        self._workers: dict[str, list[mp.Process]] = {}
        self._litapi_instances: dict[str, LitAPI] = {}
        self._dynamic_endpoints: dict[str, dict[str, Any]] | None = None
        self._workers_setup_status: dict[str, Any] = {}
        # model_name -> actual model directory path (for .lma artifacts extracted to cache)
        self._artifact_model_paths: dict[str, Path] = {}
        # Shared memory buffer for zero-copy transport of large payloads
        self._shm_buffer = ShmPayloadBuffer(threshold_bytes=4096)
        # Stream routing: stream_id -> worker_id for sticky routing (per-process)
        self._stream_routing: dict[str, int] = {}
        self._stream_lock = threading.Lock()
        # Worker load tracking: model_key -> {worker_id: active_stream_count}
        self._worker_loads: dict[str, dict[int, int]] = {}
        # Global lock for model load/unload/activate to prevent race conditions
        self._model_lock = mp.RLock()

    def _scan_plain_models(self, models: list[dict[str, Any]]) -> None:
        """Scan plain model subdirectories."""
        import yaml
        for model_dir in self.repo_path.iterdir():
            if not model_dir.is_dir():
                continue
            for version_dir in model_dir.iterdir():
                if not version_dir.is_dir():
                    continue
                model_py = version_dir / "model.py"
                config_yaml = version_dir / "config.yaml"
                is_ensemble = False
                if config_yaml.exists():
                    try:
                        with open(config_yaml, "r", encoding="utf-8") as f:
                            cfg = yaml.safe_load(f) or {}
                        is_ensemble = "ensemble" in cfg
                    except Exception:
                        pass
                if model_py.exists() or is_ensemble:
                    models.append({
                        "name": model_dir.name,
                        "version": version_dir.name,
                        "path": str(version_dir),
                        "has_config": config_yaml.exists(),
                        "type": "ensemble" if is_ensemble else "litapi",
                    })

    def _scan_artifact_models(self, models: list[dict[str, Any]]) -> None:
        """Scan .lma artifacts and extract to cache."""
        import yaml
        from light_server.artifact.cache import ArtifactCache
        cache = ArtifactCache()
        for lma_file in self.repo_path.glob("*.lma"):
            try:
                model_dir = cache.get_or_extract(lma_file)
                self._artifact_model_paths[model_dir.name] = model_dir
                for version_dir in model_dir.iterdir():
                    if not version_dir.is_dir():
                        continue
                    model_py = version_dir / "model.py"
                    config_yaml = version_dir / "config.yaml"
                    is_ensemble = False
                    if config_yaml.exists():
                        try:
                            with open(config_yaml, "r", encoding="utf-8") as f:
                                cfg = yaml.safe_load(f) or {}
                            is_ensemble = "ensemble" in cfg
                        except Exception:
                            pass
                    if model_py.exists() or is_ensemble:
                        models.append({
                            "name": model_dir.name,
                            "version": version_dir.name,
                            "path": str(version_dir),
                            "has_config": config_yaml.exists(),
                            "type": "ensemble" if is_ensemble else "litapi",
                            "artifact_source": str(lma_file),
                        })
            except Exception as e:
                logger.warning(f"Failed to scan artifact {lma_file}: {e}")

    def list_repository(self) -> list[dict[str, Any]]:
        """Scan model_repo directory and return available models.

        Supports both plain model subdirectories and .lma artifact files.
        """
        models: list[dict[str, Any]] = []
        if not self.repo_path.exists():
            return models

        self._scan_plain_models(models)
        self._scan_artifact_models(models)
        return models

    def _load_dynamic_endpoints(self) -> dict[str, dict[str, Any]]:
        """Scan model_repo for *_endpoint.py files and load them.

        Each file defines a custom endpoint registered at ``/{stem}``
        where ``stem`` is the filename without the ``_endpoint.py`` suffix.
        The module must expose a ``handler`` callable.
        An optional ``methods`` list controls HTTP methods (default ["GET"]).
        """
        endpoints: dict[str, dict[str, Any]] = {}
        if not self.repo_path.exists():
            return endpoints
        for py_file in self.repo_path.glob("*_endpoint.py"):
            stem = py_file.stem
            if not stem.endswith("_endpoint"):
                continue
            route = stem[:-9]  # strip "_endpoint"
            try:
                module = load_module_from_file(py_file)
                handler = getattr(module, "handler", None)
                if handler is None or not callable(handler):
                    logger.warning(f"Endpoint file {py_file} has no callable 'handler'")
                    continue
                methods = getattr(module, "methods", ["GET"])
                if isinstance(methods, str):
                    methods = [methods]
                endpoints[route] = {"handler": handler, "methods": methods}
            except Exception as e:
                logger.warning(f"Failed to load endpoint {py_file}: {e}")
        return endpoints

    def load_dynamic_endpoints(self) -> dict[str, dict[str, Any]]:
        """Return cached dynamic endpoints, computing once on first call."""
        if self._dynamic_endpoints is None:
            self._dynamic_endpoints = self._load_dynamic_endpoints()
        return self._dynamic_endpoints

    def get_litapi(self, name: str, version: str | None) -> LitAPI | None:
        """Return the LitAPI instance for a loaded model version.

        If ``version`` is None, uses the currently active version.
        """
        if version is None:
            version = self.registry.get_active_version(name)
        if version is None:
            return None
        key = self._worker_key(name, version)
        return self._litapi_instances.get(key)

    def _resolve_model_base(self, name: str) -> Path:
        """Return the base directory for a model (either plain or from artifact cache)."""
        if name in self._artifact_model_paths:
            return self._artifact_model_paths[name]
        target = (self.repo_path / name).resolve()
        repo = self.repo_path.resolve()
        if not str(target).startswith(str(repo) + os.sep) and target != repo:
            raise ValidationError(f"model path escapes repository: {target}")
        return target

    def load(self, name: str, version: str = "1") -> bool:
        """Load a model version from the repository.

        Spins up inference worker processes (or parses an ensemble DAG)
        and registers the model in :class:`ModelRegistry`.

        Args:
            name: Model name (must match a directory in the repo).
            version: Version string, defaults to ``"1"``.

        Returns:
            ``True`` if the model was loaded successfully.
        """
        try:
            validate_model_name(name)
            validate_version(version)
        except ValidationError as exc:
            logger.warning(f"Invalid model name or version: {exc}")
            return False

        key = self._worker_key(name, version)
        with self._model_lock:
            if key in self._workers:
                logger.info(f"Model {name} version {version} is already loaded")
                return True
            # Placeholder to prevent concurrent threads from starting duplicate workers
            self._workers[key] = []

        success = False
        try:
            model_dir = self._resolve_model_base(name) / version
            if not model_dir.exists():
                logger.error(f"Model directory not found: {model_dir}")
                if self.system_metrics:
                    self.system_metrics.record_model_load(name, version, success=False)
                return False

            model_py = model_dir / "model.py"
            config_yaml = model_dir / "config.yaml"

            # Detect ensemble: config.yaml contains 'ensemble' block
            import yaml
            is_ensemble = False
            if config_yaml.exists():
                try:
                    with open(config_yaml, "r", encoding="utf-8") as f:
                        cfg = yaml.safe_load(f) or {}
                    is_ensemble = "ensemble" in cfg
                except Exception:
                    pass

            if not model_py.exists() and not is_ensemble:
                logger.error(f"Neither model.py nor ensemble config found in {model_dir}")
                if self.system_metrics:
                    self.system_metrics.record_model_load(name, version, success=False)
                return False

            model_config = self._load_model_config(config_yaml)

            if is_ensemble:
                with self._model_lock:
                    if key in self._workers and self._workers[key]:
                        logger.info(f"Model {name} version {version} is already loaded")
                        return True
                    success = self._load_ensemble(name, version, model_config)
                if self.system_metrics:
                    self.system_metrics.record_model_load(name, version, success=success)
                return success

            success = self._load_litapi(name, version, model_py, model_config)
            if self.system_metrics:
                self.system_metrics.record_model_load(name, version, success=success)
            return success
        finally:
            # If loading failed, remove the placeholder
            if not success:
                with self._model_lock:
                    if key in self._workers and self._workers[key] == []:
                        self._workers.pop(key, None)

    def _load_ensemble(self, name: str, version: str, model_config: dict[str, Any]) -> bool:
        """Load an ensemble model (no workers, just parse DAG)."""
        try:
            self.registry.register(name, version, model_config, model_type="ensemble")
            ensemble_config = EnsembleParser.parse(model_config)
            # Store parsed ensemble config in registry entry for runtime use
            self.registry.update_entry(name, version, ensemble_config=ensemble_config)

            self.registry.set_status(name, version, "READY")

            orch = self.get_orchestration()
            model_strategy = next(
                (m for m in orch.get("models", []) if m.get("name") == name), {}
            )
            default_version = model_strategy.get("default_version")
            current_active = self.registry.get_active_version(name)
            if current_active is None:
                if default_version is not None:
                    if version == default_version:
                        self.registry.activate_version(name, version)
                else:
                    self.registry.activate_version(name, version)

            logger.info(f"Ensemble {name} version {version} loaded successfully")
            return True
        except Exception as e:
            logger.exception(f"Failed to load ensemble {name} version {version}: {e}")
            self.registry.set_status(name, version, "ERROR")
            return False

    def _load_litapi(self, name: str, version: str, model_py: Path, model_config: dict[str, Any]) -> bool:
        """Load a LitAPI model with worker processes."""
        self.registry.register(name, version, model_config, model_type="litapi", model_dir=str(model_py.parent))

        try:
            from light_server.core.loops import AdaptiveBatchedLoop

            LitAPIClass = load_litapi_from_file(model_py, suppress_prometheus=True)
            max_batch_size = model_config.get("max_batch_size", 1)
            if model_config.get("bidirectional", False):
                from light_server.core.loops import BidirectionalStreamingLoop
                loop = BidirectionalStreamingLoop()
            elif model_config.get("continuous_batching", False):
                from litserve.loops import ContinuousBatchingLoop
                loop = ContinuousBatchingLoop(
                    max_sequence_length=model_config.get("max_sequence_length", 2048)
                )
            elif max_batch_size > 1:
                loop = AdaptiveBatchedLoop()
            else:
                loop = "auto"
            lit_api = LitAPIClass(
                max_batch_size=max_batch_size,
                batch_timeout=model_config.get("batch_timeout", 0.0),
                api_path=model_config.get("api_path", "/predict"),
                stream=model_config.get("stream", False),
                loop=loop,
            )
            lit_api.config = model_config
            lit_api.pre_setup()

            accelerator = model_config.get("accelerator", "cpu")
            devices = model_config.get("devices", 1)
            workers_per_device = model_config.get("workers_per_device", 1)
            if isinstance(devices, str) and devices == "auto":
                devices = 1
            if not isinstance(devices, int):
                devices = 1
            total_workers = devices * workers_per_device
            max_queue_size = model_config.get("max_queue_size", 1000)
            worker_queues = [self._manager.Queue(maxsize=max_queue_size) for _ in range(total_workers)]
            self.registry.set_worker_queues(name, version, worker_queues)
            # Backward-compat: also set the legacy single queue (points to worker 0)
            self.registry.set_queue(name, version, worker_queues[0])

            workers = self._launch_workers(
                name, version, str(model_py), model_config, worker_queues
            )
            key = self._worker_key(name, version)

            with self._model_lock:
                if key in self._workers and self._workers[key]:
                    # Another thread already loaded this model
                    for w in workers:
                        w.terminate()
                        w.join(timeout=2)
                    logger.info(f"Model {name} version {version} loaded by another thread")
                    return True
                self._workers[key] = workers
                self._litapi_instances[key] = lit_api

            self._wait_for_ready(key, workers)

            with self._model_lock:
                self.registry.set_status(name, version, "READY")

                orch = self.get_orchestration()
                model_strategy = next(
                    (m for m in orch.get("models", []) if m.get("name") == name), {}
                )
                default_version = model_strategy.get("default_version")
                current_active = self.registry.get_active_version(name)
                if current_active is None:
                    if default_version is not None:
                        if version == default_version:
                            self.registry.activate_version(name, version)
                    else:
                        self.registry.activate_version(name, version)

                self._enforce_max_versions(name)

                if self.system_metrics:
                    self.system_metrics.set_active_workers(name, version, len(workers))

            logger.info(f"Model {name} version {version} loaded successfully")
            return True

        except Exception as e:
            logger.exception(f"Failed to load model {name} version {version}: {e}")
            with self._model_lock:
                self.registry.set_status(name, version, "ERROR")
            return False

    def reload(self, name: str, version: str | None = None) -> bool:
        """Reload a model version: unload then load again.

        Preserves the active version state. If version is None, reloads
        the currently active version.
        """
        try:
            validate_model_name(name)
            if version is not None:
                validate_version(version)
        except ValidationError as exc:
            logger.warning(f"Invalid model name or version: {exc}")
            return False

        if version is None:
            version = self.registry.get_active_version(name)
        if version is None:
            logger.warning(f"No active version for {name} to reload")
            return False

        # Capture current config from registry
        entry = self.registry.get(name, version)
        if entry is None:
            logger.warning(f"Model {name} version {version} is not loaded")
            return False

        model_config = entry.get("config", {})
        was_active = self.registry.get_active_version(name) == version

        logger.info(f"Reloading {name} version {version}")
        if not self._unload_version(name, version):
            logger.error(f"Failed to unload {name} version {version} during reload")
            return False

        # Small delay to ensure workers are fully terminated
        time.sleep(0.5)

        success = self.load(name, version)
        if success and was_active:
            self.registry.activate_version(name, version)

        if success:
            logger.info(f"Reloaded {name} version {version} successfully")
        else:
            logger.error(f"Failed to reload {name} version {version}")
        return success

    def delete_version(self, name: str, version: str) -> bool:
        """Delete a model version from the repository.

        Unloads the version if it is loaded, then removes the version
        directory from the filesystem.
        """
        try:
            validate_model_name(name)
            validate_version(version)
        except ValidationError as exc:
            logger.warning(f"Invalid model name or version: {exc}")
            return False

        key = self._worker_key(name, version)

        # Unload if currently loaded
        if key in self._workers:
            logger.info(f"Unloading {name} version {version} before deletion")
            if not self._unload_version(name, version):
                logger.error(f"Failed to unload {name} version {version} before deletion")
                return False

        # Remove version directory
        model_dir = self._resolve_model_base(name) / version
        if not model_dir.exists():
            logger.warning(f"Version directory not found: {model_dir}")
            return True  # Already gone

        try:
            import shutil
            shutil.rmtree(model_dir)
            logger.info(f"Deleted {name} version {version} from {model_dir}")
        except Exception as e:
            logger.exception(f"Failed to delete {model_dir}: {e}")
            return False

        return True

    def unload(self, name: str, version: str | None = None) -> bool:
        """Unload a model version and stop its workers.

        If version is None, unloads all versions of the model.
        """
        try:
            validate_model_name(name)
            if version is not None:
                validate_version(version)
        except ValidationError as exc:
            logger.warning(f"Invalid model name or version: {exc}")
            return False

        if version is not None:
            return self._unload_version(name, version)

        unloaded_any = False
        with self._model_lock:
            keys = [k for k in self._workers if k.startswith(f"{name}_")]
        for key in keys:
            v = key[len(name) + 1:]
            if self._unload_version(name, v):
                unloaded_any = True

        return unloaded_any

    def _unload_version(self, name: str, version: str) -> bool:
        key = self._worker_key(name, version)
        workers_to_stop: list[mp.Process] = []
        lit_api: LitAPI | None = None

        with self._model_lock:
            entry = self.registry.get(name, version)
            is_ensemble = entry is not None and entry.get("model_type") == "ensemble"

            if key not in self._workers and not is_ensemble:
                logger.warning(f"Model {name} version {version} is not loaded")
                return False

            self.registry.set_status(name, version, "UNLOADING")

            if not is_ensemble:
                # Close all per-worker request queues
                worker_queues = self.registry.get_worker_queues(name, version)
                if worker_queues:
                    for q in worker_queues:
                        if hasattr(q, "close"):
                            try:
                                q.close()
                                q.join_thread()
                            except Exception as e:
                                logger.warning(f"Error closing queue for {name} v{version}: {e}")
                # Also close the legacy single queue if it wasn't in worker_queues
                q_legacy = self.registry.get_queue(name, version)
                if q_legacy is not None:
                    if hasattr(q_legacy, "close"):
                        try:
                            q_legacy.close()
                            q_legacy.join_thread()
                        except Exception as e:
                            logger.warning(f"Error closing queue for {name} v{version}: {e}")

                # Clean up stream routing and worker loads for this model
                self._worker_loads.pop(key, None)
                with self._stream_lock:
                    self._stream_routing = {
                        sid: wid for sid, wid in self._stream_routing.items()
                        if not sid.startswith(f"{key}-")
                    }

                # Pop workers (terminate outside the lock)
                workers_to_stop = self._workers.pop(key, [])

                # Pop LitAPI instance (teardown outside the lock)
                lit_api = self._litapi_instances.pop(key, None)

                # Clean up per-worker status entries in the manager.dict()
                setup_status = self._workers_setup_status.pop(key, None)
                if setup_status is not None:
                    prefix = f"{key}_"
                    for k in list(setup_status.keys()):
                        if k.startswith(prefix):
                            try:
                                del setup_status[k]
                            except KeyError:
                                pass

            self.registry.remove(name, version)

            # If we just unloaded the active version, clear it
            if self.registry.get_active_version(name) == version:
                self.registry.deactivate(name)
                # Try to auto-activate another ready version
                for e in self.registry.list_versions(name):
                    if e.get("status") == "READY":
                        self.registry.activate_version(name, e["version"])
                        break

            if self.system_metrics:
                self.system_metrics.record_model_unload(name, version)
                self.system_metrics.set_active_workers(name, version, 0)

            # Purge artifact cache if this model came from an artifact and no versions remain loaded
            if name in self._artifact_model_paths:
                remaining = self.registry.list_versions(name)
                if not remaining:
                    try:
                        from light_server.artifact.cache import ArtifactCache
                        ArtifactCache().purge(name)
                        self._artifact_model_paths.pop(name, None)
                    except Exception as e:
                        logger.warning(f"Failed to purge artifact cache for {name}: {e}")

        # Lock released: terminate workers and teardown
        for worker in workers_to_stop:
            try:
                worker.terminate()
                worker.join(timeout=5)
                if worker.is_alive():
                    worker.kill()
                    worker.join(timeout=2)
            except Exception as e:
                logger.error(f"Error terminating worker for {name} v{version}: {e}")

        if lit_api is not None:
            try:
                lit_api.teardown()
            except Exception as e:
                logger.warning(f"teardown hook failed for {name} v{version}: {e}")

        logger.info(f"Model {name} version {version} unloaded")
        return True

    @staticmethod
    def _next_uid(name: str, version: str) -> str:
        """Generate a unique request id (process-safe, no locks)."""
        return _make_uid(name, version)

    @staticmethod
    def _pick_worker_random(num_workers: int) -> int:
        """Random worker selection for regular requests."""
        return _pick_worker_random(num_workers)

    def _pick_worker_least_loaded(self, key: str) -> int:
        """Pick the worker with the fewest active streams."""
        return _pick_worker_least_loaded(self._worker_loads, key)

    def infer(self, name: str, payload: dict[str, Any], version: str | None = None, response_queue_id: int = 0) -> str:
        """Submit an inference request for a model."""
        return submit_infer(
            self.registry, self._shm_buffer, self.system_metrics,
            name, payload, version=version, response_queue_id=response_queue_id,
        )

    def infer_stream_open(self, name: str, stream_id: str, version: str | None = None, response_queue_id: int = 0) -> int:
        """Open a bidirectional stream. Returns the assigned worker_id."""
        return submit_stream_open(
            self.registry, self._stream_routing, self._stream_lock, self._worker_loads,
            name, stream_id, version=version, response_queue_id=response_queue_id,
        )

    def infer_stream_chunk(self, name: str, stream_id: str, chunk: dict[str, Any], version: str | None = None, response_queue_id: int = 0) -> str:
        """Send a chunk into an active bidirectional stream."""
        return submit_stream_chunk(
            self.registry, self._stream_routing,
            name, stream_id, chunk, version=version, response_queue_id=response_queue_id,
        )

    def infer_stream_close(self, name: str, stream_id: str, version: str | None = None, response_queue_id: int = 0) -> None:
        """Close a bidirectional stream."""
        submit_stream_close(
            self.registry, self._stream_routing, self._worker_loads,
            name, stream_id, version=version, response_queue_id=response_queue_id,
        )

    def infer_stream_cancel(self, name: str, stream_id: str, version: str | None = None, response_queue_id: int = 0) -> None:
        """Cancel a bidirectional stream immediately."""
        submit_stream_cancel(
            self.registry, self._stream_routing, self._worker_loads,
            name, stream_id, version=version, response_queue_id=response_queue_id,
        )

    def activate(self, name: str, version: str) -> bool:
        """Activate a specific version for default routing.

        After activation, inference requests that do not specify a version
        will be routed to this version.

        Args:
            name: Model name.
            version: Version to activate.

        Returns:
            ``True`` if the version was activated (i.e. it exists and is ready).
        """
        try:
            validate_model_name(name)
            validate_version(version)
        except ValidationError as exc:
            logger.warning(f"Invalid model name or version: {exc}")
            return False
        with self._model_lock:
            success = self.registry.activate_version(name, version)
        if success and self.system_metrics:
            self.system_metrics.record_version_switch(name)
        return success

    def get_orchestration(self) -> dict[str, Any]:
        """Read orchestration config from model_repo/orchestration.yaml."""
        import yaml
        config_path = self.repo_path / "orchestration.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def set_orchestration(self, data: dict[str, Any]) -> bool:
        """Write orchestration config to model_repo/orchestration.yaml."""
        import yaml
        config_path = self.repo_path / "orchestration.yaml"
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            return True
        except Exception as e:
            logger.exception(f"Failed to write orchestration config: {e}")
            return False

    def get_version_config(self, name: str, version: str) -> dict[str, Any]:
        """Read version-level config from model_repo/{name}/{version}/config.yaml."""
        try:
            validate_model_name(name)
            validate_version(version)
        except ValidationError as exc:
            logger.warning(f"Invalid model name or version: {exc}")
            return {}
        import yaml
        config_path = self._resolve_model_base(name) / version / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def set_version_config(self, name: str, version: str, data: dict[str, Any]) -> bool:
        """Write version-level config to model_repo/{name}/{version}/config.yaml."""
        try:
            validate_model_name(name)
            validate_version(version)
        except ValidationError as exc:
            logger.warning(f"Invalid model name or version: {exc}")
            return False
        import yaml
        config_path = self._resolve_model_base(name) / version / "config.yaml"
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            return True
        except Exception as e:
            logger.exception(f"Failed to write version config: {e}")
            return False

    def shutdown(self) -> None:
        """Release all shared memory and other resources."""
        self._shm_buffer.shutdown()
        # Shut down the multiprocessing Manager to prevent orphan processes
        if hasattr(self, "_manager") and self._manager is not None:
            try:
                self._manager.shutdown()
            except Exception:
                pass
            self._manager = None

    def _enforce_max_versions(self, name: str) -> None:
        """Unload oldest versions if max_loaded_versions is exceeded."""
        orch = self.get_orchestration()
        model_strategy = next(
            (m for m in orch.get("models", []) if m.get("name") == name), {}
        )
        max_versions = model_strategy.get("max_loaded_versions")
        if max_versions is None:
            return
        versions = self.registry.list_versions(name)
        ready = [v for v in versions if v.get("status") == "READY"]
        ready.sort(key=lambda x: x["version"])
        while len(ready) > max_versions:
            to_unload = ready.pop(0)
            v = to_unload["version"]
            logger.info(f"max_loaded_versions ({max_versions}) exceeded, "
                        f"unloading {name} version {v}")
            self._unload_version(name, v)

    @staticmethod
    def _worker_key(name: str, version: str) -> str:
        return f"{name}_{version}"

    def _load_model_config(self, config_yaml: Path) -> dict[str, Any]:
        import yaml
        config: dict[str, Any] = {}
        if config_yaml.exists():
            with open(config_yaml, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

        # Continuous batching manages concurrency internally; force single worker
        if config.get("continuous_batching", False):
            wp = config.get("workers_per_device", 1)
            if wp != 1:
                logger.warning(
                    f"continuous_batching enabled; forcing workers_per_device=1 (was {wp})"
                )
            config["workers_per_device"] = 1

        return config

    def _launch_workers(self, name: str, version: str, model_py_path: str, config: dict[str, Any], worker_queues: list[Any]) -> list[mp.Process]:
        """Launch inference worker processes for a model version."""
        workers = []
        accelerator = config.get("accelerator", "cpu")
        devices = config.get("devices", 1)
        workers_per_device = config.get("workers_per_device", 1)

        if isinstance(devices, str) and devices == "auto":
            devices = 1
        if not isinstance(devices, int):
            devices = 1

        device_list = [f"{accelerator}:{i}" for i in range(devices)]

        total_workers = len(device_list) * workers_per_device
        key = self._worker_key(name, version)
        workers_setup_status = self._manager.dict()
        self._workers_setup_status[key] = workers_setup_status

        for worker_id in range(total_workers):
            device = device_list[worker_id % len(device_list)]
            workers_setup_status[f"{key}_{worker_id}"] = "starting"

            p = self._mp_ctx.Process(
                target=_inference_worker_wrapper,
                args=(name, version, model_py_path, config, device, worker_id, worker_queues[worker_id], self.transport, workers_setup_status, self.log_queue),
                name=f"inference-worker-{name}-{version}-{worker_id}",
            )
            p.start()
            workers.append(p)

        return workers

    def _wait_for_ready(self, key: str, workers: list[mp.Process], timeout: float = 60.0) -> None:
        start = time.time()
        status_dict = self._workers_setup_status.get(key, {})
        while time.time() - start < timeout:
            if not all(w.is_alive() for w in workers):
                raise WorkerCrashedError("One or more workers died during startup")
            ready_count = sum(1 for v in status_dict.values() if v == "ready")
            if ready_count == len(workers):
                return
            time.sleep(0.1)
        raise InferenceTimeoutError("Workers did not become ready in time")


class _null_context:
    """No-op context manager for optional locking."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _make_uid(name: str, version: str) -> str:
    """Generate a unique request id (process-safe, no locks)."""
    return f"{name}_{version}-{uuid.uuid4().hex}-{time.monotonic_ns()}"


def _pick_worker_random(num_workers: int) -> int:
    """Random worker selection for regular requests."""
    return random.randint(0, num_workers - 1)


def _pick_worker_least_loaded(worker_loads: dict[str, dict[int, int]], key: str) -> int:
    """Pick the worker with the fewest active streams."""
    loads = worker_loads.get(key, {})
    if not loads:
        return 0
    return min(loads, key=loads.get)


def submit_infer(
    registry: ModelRegistry,
    shm_buffer: Any,
    system_metrics: Any,
    name: str,
    payload: dict[str, Any],
    version: str | None = None,
    response_queue_id: int = 0,
) -> str:
    """Submit an inference request for a model (standalone, process-safe).

    The request is placed on a per-worker queue.  The caller should
    await the corresponding uid in the shared response buffer.
    """
    validate_model_name(name)
    if version is not None:
        validate_version(version)

    if version is None:
        version = registry.get_active_version(name)
        if version is None:
            raise ModelNotFoundError(f"Model {name} has no active version")

    if not registry.is_ready(name, version):
        raise ModelNotReadyError(f"Model {name} version {version} is not ready")

    worker_queues = registry.get_worker_queues(name, version)
    if worker_queues is None:
        # Fallback: backward compat for tests that only set a single queue
        q = registry.get_queue(name, version)
        if q is None:
            raise ModelNotFoundError(f"Model {name} version {version} has no request queues")
        uid = _make_uid(name, version)
        entry = registry.get(name, version)
        max_batch_size = (entry.get("config") or {}).get("max_batch_size", 1) if entry else 1
        item = (response_queue_id, uid, time.monotonic(), payload)
        if max_batch_size > 1:
            mode, data = shm_buffer.offload(payload)
            item = (response_queue_id, uid, time.monotonic(), (mode, data))
        try:
            q.put_nowait(item)
        except queue.Full:
            raise QueueFullError(f"Queue for {name} v{version} is full")
        if system_metrics:
            system_metrics.inc_queue_depth(name, version)
        return uid

    worker_id = _pick_worker_random(len(worker_queues))
    q = worker_queues[worker_id]

    uid = _make_uid(name, version)
    entry = registry.get(name, version)
    max_batch_size = (entry.get("config") or {}).get("max_batch_size", 1) if entry else 1
    item = (response_queue_id, uid, time.monotonic(), payload)
    if max_batch_size > 1:
        mode, data = shm_buffer.offload(payload)
        item = (response_queue_id, uid, time.monotonic(), (mode, data))
    try:
        q.put_nowait(item)
    except queue.Full:
        raise QueueFullError(f"Queue for {name} v{version} is full")
    if system_metrics:
        system_metrics.inc_queue_depth(name, version)
    return uid


def submit_stream_open(
    registry: ModelRegistry,
    stream_routing: dict[str, int],
    stream_lock: threading.Lock,
    worker_loads: dict[str, dict[int, int]],
    name: str,
    stream_id: str,
    version: str | None = None,
    response_queue_id: int = 0,
) -> int:
    """Open a bidirectional stream. Returns the assigned worker_id."""
    validate_model_name(name)
    if version is not None:
        validate_version(version)

    if version is None:
        version = registry.get_active_version(name)
        if version is None:
            raise ModelNotFoundError(f"Model {name} has no active version")

    if not registry.is_ready(name, version):
        raise ModelNotReadyError(f"Model {name} version {version} is not ready")

    worker_queues = registry.get_worker_queues(name, version)
    if worker_queues is None:
        raise ModelNotFoundError(f"Model {name} version {version} has no request queues")

    key = ModelManager._worker_key(name, version)
    worker_id = _pick_worker_least_loaded(worker_loads, key)
    _lock_ctx = stream_lock if stream_lock is not None else _null_context()
    with _lock_ctx:
        stream_routing[stream_id] = worker_id

    loads = worker_loads.setdefault(key, {})
    loads[worker_id] = loads.get(worker_id, 0) + 1

    q = worker_queues[worker_id]
    uid = _make_uid(name, version)
    payload = {"_stream_meta": {"msg_type": "STREAM_OPEN", "stream_id": stream_id}}
    try:
        q.put_nowait((response_queue_id, uid, time.monotonic(), payload))
    except queue.Full:
        # Roll back stream routing and load tracking
        with _lock_ctx:
            stream_routing.pop(stream_id, None)
        loads[worker_id] = max(0, loads.get(worker_id, 0) - 1)
        raise QueueFullError(f"Queue for {name} v{version} is full")
    return worker_id


def submit_stream_chunk(
    registry: ModelRegistry,
    stream_routing: dict[str, int],
    name: str,
    stream_id: str,
    chunk: dict[str, Any],
    version: str | None = None,
    response_queue_id: int = 0,
) -> str:
    """Send a chunk into an active bidirectional stream."""
    validate_model_name(name)
    if version is not None:
        validate_version(version)

    if version is None:
        version = registry.get_active_version(name)

    worker_id = stream_routing.get(stream_id)
    if worker_id is None:
        raise ModelNotFoundError(f"Stream {stream_id} is not open")

    worker_queues = registry.get_worker_queues(name, version)
    if worker_queues is None or worker_id >= len(worker_queues):
        raise ModelNotFoundError(f"Model {name} worker queues unavailable")

    q = worker_queues[worker_id]
    uid = _make_uid(name, version)
    payload = {"_stream_meta": {"msg_type": "STREAM_CHUNK", "stream_id": stream_id}, **chunk}
    try:
        q.put_nowait((response_queue_id, uid, time.monotonic(), payload))
    except queue.Full:
        raise QueueFullError(f"Queue for {name} v{version} is full")
    return uid


def submit_stream_close(
    registry: ModelRegistry,
    stream_routing: dict[str, int],
    worker_loads: dict[str, dict[int, int]],
    name: str,
    stream_id: str,
    version: str | None = None,
    response_queue_id: int = 0,
) -> None:
    """Close a bidirectional stream."""
    validate_model_name(name)
    if version is not None:
        validate_version(version)

    if version is None:
        version = registry.get_active_version(name)

    worker_id = stream_routing.pop(stream_id, None)
    if worker_id is None:
        return

    key = ModelManager._worker_key(name, version) if version else None
    if key:
        loads = worker_loads.get(key, {})
        loads[worker_id] = max(0, loads.get(worker_id, 0) - 1)

    worker_queues = registry.get_worker_queues(name, version)
    if worker_queues is None or worker_id >= len(worker_queues):
        return

    q = worker_queues[worker_id]
    uid = _make_uid(name, version)
    payload = {"_stream_meta": {"msg_type": "STREAM_CLOSE", "stream_id": stream_id}}
    try:
        q.put((response_queue_id, uid, time.monotonic(), payload), timeout=1.0)
    except queue.Full:
        logger.error(f"Queue full: STREAM_CLOSE dropped for {name} v{version}")


def submit_stream_cancel(
    registry: ModelRegistry,
    stream_routing: dict[str, int],
    worker_loads: dict[str, dict[int, int]],
    name: str,
    stream_id: str,
    version: str | None = None,
    response_queue_id: int = 0,
) -> None:
    """Cancel a bidirectional stream immediately."""
    validate_model_name(name)
    if version is not None:
        validate_version(version)

    if version is None:
        version = registry.get_active_version(name)

    worker_id = stream_routing.pop(stream_id, None)
    if worker_id is None:
        return

    key = ModelManager._worker_key(name, version) if version else None
    if key:
        loads = worker_loads.get(key, {})
        loads[worker_id] = max(0, loads.get(worker_id, 0) - 1)

    worker_queues = registry.get_worker_queues(name, version)
    if worker_queues is None or worker_id >= len(worker_queues):
        return

    q = worker_queues[worker_id]
    uid = _make_uid(name, version)
    payload = {"_stream_meta": {"msg_type": "STREAM_CANCEL", "stream_id": stream_id}}
    try:
        q.put((response_queue_id, uid, time.monotonic(), payload), timeout=1.0)
    except queue.Full:
        logger.error(f"Queue full: STREAM_CANCEL dropped for {name} v{version}")


def _scan_files(model_dir: Path, patterns: list[str]) -> dict[str, float]:
    """Scan model_dir for files matching any of the glob patterns. Returns {path: mtime}."""
    result: dict[str, float] = {}
    if not model_dir.exists():
        return result
    for root, _dirs, files in os.walk(model_dir):
        for filename in files:
            filepath = os.path.join(root, filename)
            rel = os.path.relpath(filepath, model_dir)
            if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(filename, pat) for pat in patterns):
                try:
                    result[filepath] = os.path.getmtime(filepath)
                except OSError:
                    pass
    return result


def _start_file_watcher(
    lit_api: Any,
    model_dir: Path,
    config: dict[str, Any],
    stop_event: threading.Event | None = None,
) -> None:
    """Start a daemon thread that watches model_dir for changed files and notifies the model."""
    import importlib.util
    import sys

    patterns = config.get("hot_reload_patterns", ["*.py"])
    interval = config.get("hot_reload_interval", 1.0)

    def watcher() -> None:
        mtimes: dict[str, float] = {}
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            time.sleep(interval)
            if stop_event is not None and stop_event.is_set():
                break
            current = _scan_files(model_dir, patterns)
            changed_files: list[str] = []
            for path, mtime in current.items():
                last = mtimes.get(path)
                if last is None:
                    mtimes[path] = mtime
                    continue
                if mtime > last:
                    mtimes[path] = mtime
                    changed_files.append(path)

            if not changed_files:
                continue

            # Notify the model via callback if available
            handler = getattr(lit_api, "on_file_changed", None)
            if handler is not None and callable(handler):
                try:
                    result = handler(changed_files)
                except Exception as exc:
                    lit_api.logger.error(f"on_file_changed callback failed: {exc}")
                    result = None
            else:
                result = None

            # Fallback: auto-reload changed .py modules if callback didn't handle it
            if result is None:
                changed_py = [p for p in changed_files if p.endswith(".py")]
                for path in changed_py:
                    for mod_name, mod in list(sys.modules.items()):
                        mod_path = getattr(mod, "__file__", None)
                        if mod_path == path:
                            try:
                                spec = importlib.util.spec_from_file_location(mod_name, path)
                                if spec is not None and spec.loader is not None:
                                    spec.loader.exec_module(mod)
                                    lit_api.logger.info(f"Hot reloaded module: {mod_name}")
                            except Exception as exc:
                                lit_api.logger.error(f"Hot reload failed for {mod_name}: {exc}")

    threading.Thread(target=watcher, daemon=True, name="file-watcher").start()


def _inference_worker_wrapper(
    name: str,
    version: str,
    model_py_path: str,
    config: dict[str, Any],
    device: str,
    worker_id: int,
    request_queue: Any,
    transport: Any,
    workers_setup_status: Any,
    log_queue: Any | None = None,
) -> None:
    """Worker entry point: reconstruct LitAPI in child process from file path."""
    from litserve.callbacks.base import CallbackRunner
    from litserve.loops.loops import inference_worker as _inference_worker
    from light_server.core.loader import load_litapi_from_file

    if log_queue is not None:
        from light_server.logging.queue_handler import setup_worker_logging
        setup_worker_logging(log_queue, level=config.get("log_level", "INFO"))

    callback_runner = CallbackRunner()

    try:
        from light_server.core.loops import AdaptiveBatchedLoop

        # Reconstruct LitAPI in child process
        LitAPIClass = load_litapi_from_file(Path(model_py_path))
        max_batch_size = config.get("max_batch_size", 1)
        if config.get("bidirectional", False):
            from light_server.core.loops import BidirectionalStreamingLoop
            loop = BidirectionalStreamingLoop()
        elif config.get("continuous_batching", False):
            from litserve.loops import ContinuousBatchingLoop
            loop = ContinuousBatchingLoop(
                max_sequence_length=config.get("max_sequence_length", 2048)
            )
        elif max_batch_size > 1:
            loop = AdaptiveBatchedLoop()
        else:
            loop = "auto"
        lit_api = LitAPIClass(
            max_batch_size=max_batch_size,
            batch_timeout=config.get("batch_timeout", 0.0),
            api_path=config.get("api_path", "/predict"),
            stream=config.get("stream", False),
            loop=loop,
        )
        lit_api.config = config
        lit_api.pre_setup()

        stop_event: threading.Event | None = None
        if config.get("hot_reload", False):
            stop_event = threading.Event()
            _start_file_watcher(
                lit_api,
                Path(model_py_path).parent.resolve(),
                config,
                stop_event,
            )

        try:
            _inference_worker(
                lit_api,
                device,
                worker_id,
                request_queue,
                transport,
                workers_setup_status,
                callback_runner,
                restart_workers=False,
            )
        finally:
            if stop_event is not None:
                stop_event.set()
    except Exception as e:
        logger.exception(f"Worker {worker_id} for {name} v{version} crashed: {e}")
