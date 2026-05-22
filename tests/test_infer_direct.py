"""Direct inference test without HTTP server."""

import asyncio
import time
from pathlib import Path

import pytest

from light_server.config import Config, ModelRepositoryConfig, ServerConfig
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry
from light_server.core.server import LightServer
from litserve.transport.factory import TransportConfig, create_transport_from_config
from litserve.utils import LitAPIStatus, ResponseBufferItem


def test_load_and_infer():
    """Test loading a model and running inference directly."""
    import multiprocessing as mp
    manager = mp.Manager()
    registry = ModelRegistry(manager)

    transport_config = TransportConfig(transport_type="mp", num_consumers=1)
    transport_config.manager = manager
    transport = create_transport_from_config(transport_config)

    repo = Path(__file__).parent.parent / "model_repo"
    mm = ModelManager(repo, registry, transport=transport)

    # Load model
    success = mm.load("test_model")
    assert success, "Failed to load model"

    # Wait for ready
    time.sleep(2)
    assert registry.is_ready("test_model")

    # Submit inference
    uid = mm.infer("test_model", {"input": 4.0}, response_queue_id=0)
    print(f"Inference uid: {uid}")

    # Manually consume response from transport
    result = transport._queues[0].get(timeout=10)
    print(f"Transport result: {result}")

    assert result is not None
    uid_received, (response_data, status, response_type, worker_id) = result
    assert uid_received == uid
    assert status == LitAPIStatus.OK
    assert response_data == {"output": 16.0}

    # Unload
    mm.unload("test_model")
