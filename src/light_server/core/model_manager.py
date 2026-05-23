"""Model lifecycle manager: load, unload, inference."""

from __future__ import annotations

import fnmatch
import itertools
import logging
import multiprocessing as mp
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from light_server.config import ModelConfig
from light_server.core.ensemble import EnsembleParser
from light_server.core.loader import load_litapi_from_file
from light_server.core.registry import ModelRegistry
from light_server.core.shm_buffer import ShmPayloadBuffer
from light_server.core.validation import validate_model_name, validate_version
from litserve import LitAPI

logger = logging.getLogger(__name__)


class QueueFullError(Exception):
    """Raised when a model's request queue is at capacity."""
    pass


class ModelManager:
    """Manages loading/unloading of models and their inference workers."""

    def __init__(
        self,
        repo_path: Path,
        registry: ModelRegistry,
        transport: Any | None = None,
        callback_runner: Any | None = None,
        log_queue: Any | None = None,
        system_metrics: Any | None = None,
    ):
        self.repo_path = Path(repo_path)
        self.registry = registry
        self.transport = transport
        self.callback_runner = callback_runner
        self.log_queue = log_queue
        self.system_metrics = system_metrics
        self._workers: dict[str, list[mp.Process]] = {}
        self._litapi_instances: dict[str, LitAPI] = {}
        self._workers_setup_status: dict[str, Any] = {}
        # model_name -> actual model directory path (for .lma artifacts extracted to cache)
        self._artifact_model_paths: dict[str, Path] = {}
        # Small manager only for worker setup status (low-frequency, tiny data)
        self._setup_manager = mp.Manager()
        # Atomic uid counters: one per model+version to avoid global lock contention
        self._uid_counters: dict[str, itertools.count] = {}
        self._uid_lock = threading.Lock()
        # Shared memory buffer for zero-copy transport of large payloads
        self._shm_buffer = ShmPayloadBuffer(threshold_bytes=4096)
        # Stream routing: stream_id -> worker_id for sticky routing
        self._stream_routing: dict[str, int] = {}
        self._stream_lock = threading.Lock()
        # Worker load tracking: model_key -> {worker_id: active_stream_count}
        self._worker_loads: dict[str, dict[int, int]] = {}
        # Round-robin counter for regular requests
        self._infer_counters: dict[str, int] = {}
        self._infer_counter_lock = threading.Lock()
        # Global lock for model load/unload/activate to prevent race conditions
        self._model_lock = threading.Lock()

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

    def _resolve_model_base(self, name: str) -> Path:
        """Return the base directory for a model (either plain or from artifact cache)."""
        if name in self._artifact_model_paths:
            return self._artifact_model_paths[name]
        target = (self.repo_path / name).resolve()
        repo = self.repo_path.resolve()
        if not str(target).startswith(str(repo) + os.sep) and target != repo:
            raise ValueError(f"model path escapes repository: {target}")
        return target

    def load(self, name: str, version: str = "1", config_override: ModelConfig | None = None) -> bool:
        """Load a model version from the repository."""
        try:
            validate_model_name(name)
            validate_version(version)
        except ValueError as exc:
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

            model_config = self._load_model_config(config_yaml, config_override)

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
            entry = dict(self.registry.get(name, version) or {})
            entry["ensemble_config"] = ensemble_config
            self.registry._registry[self.registry._key(name, version)] = entry

            self.registry.set_status(name, version, "READY")

            model_cfg = self.get_model_config(name)
            default_version = model_cfg.get("default_version")
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
        self.registry.register(name, version, model_config, model_type="litapi")

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
            worker_queues = [mp.Queue(maxsize=max_queue_size) for _ in range(total_workers)]
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

                model_cfg = self.get_model_config(name)
                default_version = model_cfg.get("default_version")
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

    def unload(self, name: str, version: str | None = None) -> bool:
        """Unload a model version and stop its workers.

        If version is None, unloads all versions of the model.
        """
        try:
            validate_model_name(name)
            if version is not None:
                validate_version(version)
        except ValueError as exc:
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
                        try:
                            q.close()
                            q.join_thread()
                        except Exception as e:
                            logger.warning(f"Error closing queue for {name} v{version}: {e}")
                # Also close the legacy single queue if it wasn't in worker_queues
                q_legacy = self.registry.get_queue(name, version)
                if q_legacy is not None:
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
                self._infer_counters.pop(key, None)

                # Pop workers (terminate outside the lock)
                workers_to_stop = self._workers.pop(key, [])

                # Clean up atomic uid counter for this model version
                self._uid_counters.pop(key, None)

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
            except Exception as e:
                logger.error(f"Error terminating worker for {name} v{version}: {e}")

        if lit_api is not None:
            try:
                lit_api.teardown()
            except Exception as e:
                logger.warning(f"teardown hook failed for {name} v{version}: {e}")

        logger.info(f"Model {name} version {version} unloaded")
        return True

    def _next_uid(self, name: str, version: str) -> str:
        """Generate a unique request id."""
        key = self._worker_key(name, version)
        with self._uid_lock:
            if key not in self._uid_counters:
                self._uid_counters[key] = itertools.count()
            seq = next(self._uid_counters[key])
        return f"{key}-{seq}-{time.monotonic_ns() & 0xFFFFFFFF:08x}"

    def _pick_worker_round_robin(self, key: str, num_workers: int) -> int:
        """Round-robin worker selection for regular requests."""
        with self._infer_counter_lock:
            counter = self._infer_counters.get(key, 0)
            worker_id = counter % num_workers
            self._infer_counters[key] = counter + 1
            return worker_id

    def _pick_worker_least_loaded(self, key: str) -> int:
        """Pick the worker with the fewest active streams."""
        loads = self._worker_loads.get(key, {})
        if not loads:
            return 0
        return min(loads, key=loads.get)

    def infer(self, name: str, payload: dict[str, Any], version: str | None = None, response_queue_id: int = 0) -> str:
        """Submit an inference request for a model. Returns request uid."""
        validate_model_name(name)
        if version is not None:
            validate_version(version)

        if version is None:
            version = self.registry.get_active_version(name)
            if version is None:
                raise RuntimeError(f"Model {name} has no active version")

        if not self.registry.is_ready(name, version):
            raise RuntimeError(f"Model {name} version {version} is not ready")

        worker_queues = self.registry.get_worker_queues(name, version)
        if worker_queues is None:
            # Fallback: backward compat for tests that only set a single queue
            q = self.registry.get_queue(name, version)
            if q is None:
                raise RuntimeError(f"Model {name} version {version} has no request queues")
            uid = self._next_uid(name, version)
            entry = self.registry.get(name, version)
            max_batch_size = (entry.get("config") or {}).get("max_batch_size", 1) if entry else 1
            item = (response_queue_id, uid, time.monotonic(), payload)
            if max_batch_size > 1:
                mode, data = self._shm_buffer.offload(payload)
                item = (response_queue_id, uid, time.monotonic(), (mode, data))
            try:
                q.put_nowait(item)
            except queue.Full:
                raise QueueFullError(f"Queue for {name} v{version} is full")
            if self.system_metrics:
                self.system_metrics.inc_queue_depth(name, version)
            return uid

        key = self._worker_key(name, version)
        worker_id = self._pick_worker_round_robin(key, len(worker_queues))
        q = worker_queues[worker_id]

        uid = self._next_uid(name, version)
        entry = self.registry.get(name, version)
        max_batch_size = (entry.get("config") or {}).get("max_batch_size", 1) if entry else 1
        item = (response_queue_id, uid, time.monotonic(), payload)
        if max_batch_size > 1:
            mode, data = self._shm_buffer.offload(payload)
            item = (response_queue_id, uid, time.monotonic(), (mode, data))
        try:
            q.put_nowait(item)
        except queue.Full:
            raise QueueFullError(f"Queue for {name} v{version} is full")
        if self.system_metrics:
            self.system_metrics.inc_queue_depth(name, version)
        return uid

    def infer_stream_open(self, name: str, stream_id: str, version: str | None = None, response_queue_id: int = 0) -> int:
        """Open a bidirectional stream. Returns the assigned worker_id."""
        validate_model_name(name)
        if version is not None:
            validate_version(version)

        if version is None:
            version = self.registry.get_active_version(name)
            if version is None:
                raise RuntimeError(f"Model {name} has no active version")

        if not self.registry.is_ready(name, version):
            raise RuntimeError(f"Model {name} version {version} is not ready")

        worker_queues = self.registry.get_worker_queues(name, version)
        if worker_queues is None:
            raise RuntimeError(f"Model {name} version {version} has no request queues")

        key = self._worker_key(name, version)
        worker_id = self._pick_worker_least_loaded(key)
        with self._stream_lock:
            self._stream_routing[stream_id] = worker_id

        loads = self._worker_loads.setdefault(key, {})
        loads[worker_id] = loads.get(worker_id, 0) + 1

        q = worker_queues[worker_id]
        uid = self._next_uid(name, version)
        payload = {"_stream_meta": {"msg_type": "STREAM_OPEN", "stream_id": stream_id}}
        try:
            q.put_nowait((response_queue_id, uid, time.monotonic(), payload))
        except queue.Full:
            # Roll back stream routing and load tracking
            with self._stream_lock:
                self._stream_routing.pop(stream_id, None)
            loads[worker_id] = max(0, loads.get(worker_id, 0) - 1)
            raise QueueFullError(f"Queue for {name} v{version} is full")
        return worker_id

    def infer_stream_chunk(self, name: str, stream_id: str, chunk: dict[str, Any], version: str | None = None, response_queue_id: int = 0) -> str:
        """Send a chunk into an active bidirectional stream."""
        validate_model_name(name)
        if version is not None:
            validate_version(version)

        if version is None:
            version = self.registry.get_active_version(name)

        worker_id = self._stream_routing.get(stream_id)
        if worker_id is None:
            raise RuntimeError(f"Stream {stream_id} is not open")

        worker_queues = self.registry.get_worker_queues(name, version)
        if worker_queues is None or worker_id >= len(worker_queues):
            raise RuntimeError(f"Model {name} worker queues unavailable")

        q = worker_queues[worker_id]
        uid = self._next_uid(name, version)
        payload = {"_stream_meta": {"msg_type": "STREAM_CHUNK", "stream_id": stream_id}, **chunk}
        try:
            q.put_nowait((response_queue_id, uid, time.monotonic(), payload))
        except queue.Full:
            raise QueueFullError(f"Queue for {name} v{version} is full")
        return uid

    def infer_stream_close(self, name: str, stream_id: str, version: str | None = None, response_queue_id: int = 0) -> None:
        """Close a bidirectional stream."""
        validate_model_name(name)
        if version is not None:
            validate_version(version)

        if version is None:
            version = self.registry.get_active_version(name)

        worker_id = self._stream_routing.pop(stream_id, None)
        if worker_id is None:
            return

        key = self._worker_key(name, version) if version else None
        if key:
            loads = self._worker_loads.get(key, {})
            loads[worker_id] = max(0, loads.get(worker_id, 0) - 1)

        worker_queues = self.registry.get_worker_queues(name, version)
        if worker_queues is None or worker_id >= len(worker_queues):
            return

        q = worker_queues[worker_id]
        uid = self._next_uid(name, version)
        payload = {"_stream_meta": {"msg_type": "STREAM_CLOSE", "stream_id": stream_id}}
        try:
            q.put_nowait((response_queue_id, uid, time.monotonic(), payload))
        except queue.Full:
            logger.warning(f"Queue full dropping STREAM_CLOSE for {name} v{version}")

    def infer_stream_cancel(self, name: str, stream_id: str, version: str | None = None, response_queue_id: int = 0) -> None:
        """Cancel a bidirectional stream immediately."""
        validate_model_name(name)
        if version is not None:
            validate_version(version)

        if version is None:
            version = self.registry.get_active_version(name)

        worker_id = self._stream_routing.pop(stream_id, None)
        if worker_id is None:
            return

        key = self._worker_key(name, version) if version else None
        if key:
            loads = self._worker_loads.get(key, {})
            loads[worker_id] = max(0, loads.get(worker_id, 0) - 1)

        worker_queues = self.registry.get_worker_queues(name, version)
        if worker_queues is None or worker_id >= len(worker_queues):
            return

        q = worker_queues[worker_id]
        uid = self._next_uid(name, version)
        payload = {"_stream_meta": {"msg_type": "STREAM_CANCEL", "stream_id": stream_id}}
        try:
            q.put_nowait((response_queue_id, uid, time.monotonic(), payload))
        except queue.Full:
            logger.warning(f"Queue full dropping STREAM_CANCEL for {name} v{version}")

    def activate(self, name: str, version: str) -> bool:
        """Activate a specific version for default routing."""
        try:
            validate_model_name(name)
            validate_version(version)
        except ValueError as exc:
            logger.warning(f"Invalid model name or version: {exc}")
            return False
        with self._model_lock:
            success = self.registry.activate_version(name, version)
        if success and self.system_metrics:
            self.system_metrics.record_version_switch(name)
        return success

    def get_model_config(self, name: str) -> dict[str, Any]:
        """Read model-level config from model_repo/{name}/model_config.yaml."""
        try:
            validate_model_name(name)
        except ValueError as exc:
            logger.warning(f"Invalid model name: {exc}")
            return {}
        import yaml
        config_path = self._resolve_model_base(name) / "model_config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def shutdown(self) -> None:
        """Release all shared memory and other resources."""
        self._shm_buffer.shutdown()

    def _enforce_max_versions(self, name: str) -> None:
        """Unload oldest versions if max_loaded_versions is exceeded."""
        model_cfg = self.get_model_config(name)
        max_versions = model_cfg.get("max_loaded_versions")
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

    def _load_model_config(self, config_yaml: Path, override: ModelConfig | None = None) -> dict[str, Any]:
        import yaml
        config: dict[str, Any] = {}
        if config_yaml.exists():
            with open(config_yaml, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

        if override:
            if override.max_batch_size != 1:
                config["max_batch_size"] = override.max_batch_size
            if override.batch_timeout != 0.0:
                config["batch_timeout"] = override.batch_timeout
            if override.api_path != "/predict":
                config["api_path"] = override.api_path
            if override.stream:
                config["stream"] = override.stream
            if override.bidirectional:
                config["bidirectional"] = override.bidirectional
            if override.continuous_batching:
                config["continuous_batching"] = override.continuous_batching
            if override.max_sequence_length != 2048:
                config["max_sequence_length"] = override.max_sequence_length
            if override.accelerator:
                config["accelerator"] = override.accelerator
            if override.devices is not None:
                config["devices"] = override.devices
            if override.workers_per_device is not None:
                config["workers_per_device"] = override.workers_per_device
            if override.max_queue_size != 1000:
                config["max_queue_size"] = override.max_queue_size

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

        if accelerator == "cpu":
            device_list = ["cpu"] * devices
        else:
            device_list = [f"{accelerator}:{i}" for i in range(devices)]

        total_workers = len(device_list) * workers_per_device
        key = self._worker_key(name, version)
        workers_setup_status = self._setup_manager.dict()
        self._workers_setup_status[key] = workers_setup_status

        for worker_id in range(total_workers):
            device = device_list[worker_id % len(device_list)]
            workers_setup_status[f"{key}_{worker_id}"] = "starting"

            ctx = mp.get_context("spawn")
            p = ctx.Process(
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
                raise RuntimeError("One or more workers died during startup")
            ready_count = sum(1 for v in status_dict.values() if v == "ready")
            if ready_count > 0:
                return
            time.sleep(0.1)
        raise TimeoutError("Workers did not become ready in time")


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


def _start_file_watcher(lit_api: Any, model_dir: Path, config: dict[str, Any]) -> None:
    """Start a daemon thread that watches model_dir for changed files and notifies the model."""
    import importlib.util
    import sys
    import threading

    patterns = config.get("hot_reload_patterns", ["*.py"])
    interval = config.get("hot_reload_interval", 1.0)

    def watcher() -> None:
        mtimes: dict[str, float] = {}
        while True:
            time.sleep(interval)
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

        if config.get("hot_reload", False):
            _start_file_watcher(
                lit_api,
                Path(model_py_path).parent.resolve(),
                config,
            )

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
    except Exception as e:
        logger.exception(f"Worker {worker_id} for {name} v{version} crashed: {e}")
