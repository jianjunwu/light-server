"""Model lifecycle manager: load, unload, inference."""

from __future__ import annotations

import fnmatch
import itertools
import logging
import multiprocessing as mp
import os
import threading
import time
from pathlib import Path
from typing import Any

from light_server.config import ModelConfig
from light_server.core.ensemble import EnsembleParser
from light_server.core.loader import load_litapi_from_file
from light_server.core.registry import ModelRegistry
from light_server.core.shm_buffer import ShmPayloadBuffer
from litserve import LitAPI

logger = logging.getLogger(__name__)


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
        return self.repo_path / name

    def load(self, name: str, version: str = "1", config_override: ModelConfig | None = None) -> bool:
        """Load a model version from the repository."""
        key = self._worker_key(name, version)
        if key in self._workers:
            logger.info(f"Model {name} version {version} is already loaded")
            return True

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
            success = self._load_ensemble(name, version, model_config)
            if self.system_metrics:
                self.system_metrics.record_model_load(name, version, success=success)
            return success

        success = self._load_litapi(name, version, model_py, model_config)
        if self.system_metrics:
            self.system_metrics.record_model_load(name, version, success=success)
        return success

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
            lit_api = LitAPIClass(
                max_batch_size=max_batch_size,
                batch_timeout=model_config.get("batch_timeout", 0.0),
                api_path=model_config.get("api_path", "/predict"),
                stream=model_config.get("stream", False),
                loop=AdaptiveBatchedLoop() if max_batch_size > 1 else "auto",
            )
            lit_api.config = model_config
            lit_api.pre_setup()

            request_queue = mp.Queue()
            self.registry.set_queue(name, version, request_queue)

            workers = self._launch_workers(
                name, version, str(model_py), model_config, request_queue
            )
            key = self._worker_key(name, version)
            self._workers[key] = workers
            self._litapi_instances[key] = lit_api

            self._wait_for_ready(key, workers)
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
            self.registry.set_status(name, version, "ERROR")
            return False

    def unload(self, name: str, version: str | None = None) -> bool:
        """Unload a model version and stop its workers.

        If version is None, unloads all versions of the model.
        """
        if version is not None:
            return self._unload_version(name, version)

        unloaded_any = False
        keys = [k for k in self._workers if k.startswith(f"{name}_")]
        for key in keys:
            v = key[len(name) + 1:]
            if self._unload_version(name, v):
                unloaded_any = True

        return unloaded_any

    def _unload_version(self, name: str, version: str) -> bool:
        key = self._worker_key(name, version)
        entry = self.registry.get(name, version)
        is_ensemble = entry is not None and entry.get("model_type") == "ensemble"

        if key not in self._workers and not is_ensemble:
            logger.warning(f"Model {name} version {version} is not loaded")
            return False

        self.registry.set_status(name, version, "UNLOADING")

        if not is_ensemble:
            # Close the request queue to release pipe file descriptors
            queue = self.registry.get_queue(name, version)
            if queue is not None:
                try:
                    queue.close()
                    queue.join_thread()
                except Exception as e:
                    logger.warning(f"Error closing queue for {name} v{version}: {e}")

            for worker in self._workers.get(key, []):
                try:
                    worker.terminate()
                    worker.join(timeout=5)
                    if worker.is_alive():
                        worker.kill()
                except Exception as e:
                    logger.error(f"Error terminating worker for {name} v{version}: {e}")

            self._workers.pop(key, None)

            # Clean up atomic uid counter for this model version
            self._uid_counters.pop(key, None)

            # Invoke teardown hook on the LitAPI instance for framework-specific cleanup
            lit_api = self._litapi_instances.pop(key, None)
            if lit_api is not None:
                try:
                    lit_api.teardown()
                except Exception as e:
                    logger.warning(f"teardown hook failed for {name} v{version}: {e}")

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

        logger.info(f"Model {name} version {version} unloaded")
        return True

    def infer(self, name: str, payload: dict[str, Any], version: str | None = None, response_queue_id: int = 0) -> str:
        """Submit an inference request for a model. Returns request uid."""
        if version is None:
            version = self.registry.get_active_version(name)
            if version is None:
                raise RuntimeError(f"Model {name} has no active version")

        if not self.registry.is_ready(name, version):
            raise RuntimeError(f"Model {name} version {version} is not ready")

        queue = self.registry.get_queue(name, version)
        if queue is None:
            raise RuntimeError(f"Model {name} version {version} has no request queue")

        if self.system_metrics:
            self.system_metrics.inc_queue_depth(name, version)

        # Atomic integer uid: avoids uuid4() overhead under high QPS
        key = self._worker_key(name, version)
        with self._uid_lock:
            if key not in self._uid_counters:
                self._uid_counters[key] = itertools.count()
            seq = next(self._uid_counters[key])
        # Use hyphen separator to avoid ambiguity when model names contain underscores
        uid = f"{key}-{seq}-{time.monotonic_ns() & 0xFFFFFFFF:08x}"
        # Zero-copy: only wrap payload for batched models (AdaptiveBatchedLoop
        # knows how to unwrap).  SingleLoop models pass payload directly.
        entry = self.registry.get(name, version)
        max_batch_size = (entry.get("config") or {}).get("max_batch_size", 1) if entry else 1
        if max_batch_size > 1:
            mode, data = self._shm_buffer.offload(payload)
            queue.put((response_queue_id, uid, time.monotonic(), (mode, data)))
        else:
            queue.put((response_queue_id, uid, time.monotonic(), payload))
        return uid

    def activate(self, name: str, version: str) -> bool:
        """Activate a specific version for default routing."""
        success = self.registry.activate_version(name, version)
        if success and self.system_metrics:
            self.system_metrics.record_version_switch(name)
        return success

    def get_model_config(self, name: str) -> dict[str, Any]:
        """Read model-level config from model_repo/{name}/model_config.yaml."""
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
            if override.accelerator:
                config["accelerator"] = override.accelerator
            if override.devices is not None:
                config["devices"] = override.devices
            if override.workers_per_device is not None:
                config["workers_per_device"] = override.workers_per_device

        return config

    def _launch_workers(self, name: str, version: str, model_py_path: str, config: dict[str, Any], request_queue: Any) -> list[mp.Process]:
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
                args=(name, version, model_py_path, config, device, worker_id, request_queue, self.transport, workers_setup_status, self.log_queue),
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
        lit_api = LitAPIClass(
            max_batch_size=max_batch_size,
            batch_timeout=config.get("batch_timeout", 0.0),
            api_path=config.get("api_path", "/predict"),
            stream=config.get("stream", False),
            loop=AdaptiveBatchedLoop() if max_batch_size > 1 else "auto",
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
