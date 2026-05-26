"""Tests for worker device assignment."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry


class FakeProcess:
    """Picklable fake process that records ctor args."""

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._started = False

    def start(self) -> None:
        self._started = True

    def is_alive(self) -> bool:
        return self._started

    def terminate(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        pass

    def kill(self) -> None:
        pass


@pytest.fixture
def manager(tmp_path: Path):
    registry = ModelRegistry()
    return ModelManager(repo_path=tmp_path, registry=registry)


class TestCpuDeviceIndexing:
    """CPU accelerator should receive indexed device strings like GPU."""

    def test_cpu_devices_are_indexed(self, manager: ModelManager):
        """With devices=2 and accelerator=cpu, workers should get cpu:0 and cpu:1."""
        config = {
            "accelerator": "cpu",
            "devices": 2,
            "workers_per_device": 1,
        }
        fake_queues = [MagicMock() for _ in range(2)]

        with patch.object(manager._mp_ctx, "Process", FakeProcess):
            workers = manager._launch_workers(
                "test_model", "1", "/fake/model.py", config, fake_queues
            )

        assert len(workers) == 2
        # args[4] is the device string passed to _inference_worker_wrapper
        devices = [w._kwargs["args"][4] for w in workers]
        assert devices == ["cpu:0", "cpu:1"]

    def test_single_cpu_device(self, manager: ModelManager):
        """With devices=1 and accelerator=cpu, worker gets cpu:0."""
        config = {
            "accelerator": "cpu",
            "devices": 1,
            "workers_per_device": 1,
        }
        fake_queues = [MagicMock()]

        with patch.object(manager._mp_ctx, "Process", FakeProcess):
            workers = manager._launch_workers(
                "test_model", "1", "/fake/model.py", config, fake_queues
            )

        assert len(workers) == 1
        devices = [w._kwargs["args"][4] for w in workers]
        assert devices == ["cpu:0"]

    def test_gpu_devices_preserved(self, manager: ModelManager):
        """GPU device indexing must remain unchanged."""
        config = {
            "accelerator": "cuda",
            "devices": 2,
            "workers_per_device": 1,
        }
        fake_queues = [MagicMock() for _ in range(2)]

        with patch.object(manager._mp_ctx, "Process", FakeProcess):
            workers = manager._launch_workers(
                "test_model", "1", "/fake/model.py", config, fake_queues
            )

        devices = [w._kwargs["args"][4] for w in workers]
        assert devices == ["cuda:0", "cuda:1"]

    def test_workers_per_device_cpu(self, manager: ModelManager):
        """Multiple workers per CPU device should cycle through indexed devices."""
        config = {
            "accelerator": "cpu",
            "devices": 2,
            "workers_per_device": 2,
        }
        fake_queues = [MagicMock() for _ in range(4)]

        with patch.object(manager._mp_ctx, "Process", FakeProcess):
            workers = manager._launch_workers(
                "test_model", "1", "/fake/model.py", config, fake_queues
            )

        assert len(workers) == 4
        devices = [w._kwargs["args"][4] for w in workers]
        assert devices == ["cpu:0", "cpu:1", "cpu:0", "cpu:1"]
