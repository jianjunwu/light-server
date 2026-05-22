"""Model lifecycle manager: load, unload, inference."""

from __future__ import annotations

import logging
import multiprocessing as mp
import time
from pathlib import Path
from typing import Any

from light_server.config import ModelConfig
from light_server.core.loader import load_litapi_from_file
from light_server.core.registry import ModelRegistry
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
    ):
        self.repo_path = Path(repo_path)
        self.registry = registry
        self.transport = transport
        self.callback_runner = callback_runner
        self.log_queue = log_queue
        self._workers: dict[str, list[mp.Process]] = {}
        self._litapi_instances: dict[str, LitAPI] = {}
        self._workers_setup_status: dict[str, Any] = {}

    def list_repository(self) -> list[dict[str, Any]]:
        """Scan model_repo directory and return available models."""
        models = []
        if not self.repo_path.exists():
            return models

        for model_dir in self.repo_path.iterdir():
            if not model_dir.is_dir():
                continue
            for version_dir in model_dir.iterdir():
                if not version_dir.is_dir():
                    continue
                model_py = version_dir / "model.py"
                config_yaml = version_dir / "config.yaml"
                if model_py.exists():
                    models.append({
                        "name": model_dir.name,
                        "version": version_dir.name,
                        "path": str(version_dir),
                        "has_config": config_yaml.exists(),
                    })
        return models

    def load(self, name: str, version: str = "1", config_override: ModelConfig | None = None) -> bool:
        """Load a model from the repository."""
        if self.registry.is_ready(name):
            logger.info(f"Model {name} is already loaded")
            return True

        model_dir = self.repo_path / name / version
        if not model_dir.exists():
            logger.error(f"Model directory not found: {model_dir}")
            return False

        model_py = model_dir / "model.py"
        config_yaml = model_dir / "config.yaml"

        if not model_py.exists():
            logger.error(f"model.py not found in {model_dir}")
            return False

        model_config = self._load_model_config(config_yaml, config_override)
        self.registry.register(name, version, model_config)

        try:
            # Import and instantiate in parent to validate
            LitAPIClass = load_litapi_from_file(model_py)
            lit_api = LitAPIClass(
                max_batch_size=model_config.get("max_batch_size", 1),
                batch_timeout=model_config.get("batch_timeout", 0.0),
                api_path=model_config.get("api_path", "/predict"),
                stream=model_config.get("stream", False),
            )
            lit_api.pre_setup()

            request_queue = self.registry._manager.Queue()
            self.registry.set_queue(name, request_queue)

            # Pass file path and config to worker so it can reconstruct in child
            workers = self._launch_workers(
                name, str(model_py), model_config, request_queue
            )
            self._workers[name] = workers
            self._litapi_instances[name] = lit_api

            self._wait_for_ready(name, workers)
            self.registry.set_status(name, "READY")
            logger.info(f"Model {name} loaded successfully")
            return True

        except Exception as e:
            logger.exception(f"Failed to load model {name}: {e}")
            self.registry.set_status(name, "ERROR")
            return False

    def unload(self, name: str) -> bool:
        """Unload a model and stop its workers."""
        if name not in self._workers:
            logger.warning(f"Model {name} is not loaded")
            return False

        self.registry.set_status(name, "UNLOADING")

        for worker in self._workers.get(name, []):
            try:
                worker.terminate()
                worker.join(timeout=5)
                if worker.is_alive():
                    worker.kill()
            except Exception as e:
                logger.error(f"Error terminating worker for {name}: {e}")

        self._workers.pop(name, None)
        self._litapi_instances.pop(name, None)
        self.registry.remove(name)
        logger.info(f"Model {name} unloaded")
        return True

    def infer(self, name: str, payload: dict[str, Any], response_queue_id: int = 0) -> str:
        """Submit an inference request for a model. Returns request uid."""
        if not self.registry.is_ready(name):
            raise RuntimeError(f"Model {name} is not ready")

        queue = self.registry.get_queue(name)
        if queue is None:
            raise RuntimeError(f"Model {name} has no request queue")

        import uuid
        uid = str(uuid.uuid4())
        queue.put((response_queue_id, uid, time.monotonic(), payload))
        return uid

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

    def _launch_workers(self, name: str, model_py_path: str, config: dict[str, Any], request_queue: Any) -> list[mp.Process]:
        """Launch inference worker processes for a model."""
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
        workers_setup_status = self.registry._manager.dict()
        self._workers_setup_status[name] = workers_setup_status

        for worker_id in range(total_workers):
            device = device_list[worker_id % len(device_list)]
            workers_setup_status[f"{name}_{worker_id}"] = "starting"

            ctx = mp.get_context("spawn")
            p = ctx.Process(
                target=_inference_worker_wrapper,
                args=(model_py_path, config, device, worker_id, request_queue, self.transport, workers_setup_status, self.log_queue),
                name=f"inference-worker-{name}-{worker_id}",
            )
            p.start()
            workers.append(p)

        return workers

    def _wait_for_ready(self, name: str, workers: list[mp.Process], timeout: float = 60.0) -> None:
        start = time.time()
        status_dict = self._workers_setup_status.get(name, {})
        while time.time() - start < timeout:
            if not all(w.is_alive() for w in workers):
                raise RuntimeError("One or more workers died during startup")
            ready_count = sum(1 for v in status_dict.values() if v == "ready")
            if ready_count > 0:
                return
            time.sleep(0.1)
        raise TimeoutError("Workers did not become ready in time")


def _inference_worker_wrapper(
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
        # Reconstruct LitAPI in child process
        LitAPIClass = load_litapi_from_file(Path(model_py_path))
        lit_api = LitAPIClass(
            max_batch_size=config.get("max_batch_size", 1),
            batch_timeout=config.get("batch_timeout", 0.0),
            api_path=config.get("api_path", "/predict"),
            stream=config.get("stream", False),
        )
        lit_api.pre_setup()

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
        logger.exception(f"Worker {worker_id} crashed: {e}")
