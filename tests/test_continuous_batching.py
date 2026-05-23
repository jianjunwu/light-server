"""Tests for Continuous Batching support."""

import multiprocessing as mp
import time
from pathlib import Path

import pytest

from light_server.config import ModelConfig
from light_server.core.loader import load_litapi_from_file
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_load_cb_model_class():
    """Verify the continuous batching model class can be loaded."""
    model_py = PROJECT_ROOT / "model_repo" / "cb_model" / "1" / "model.py"
    cls = load_litapi_from_file(model_py)
    assert cls.__name__ == "CBModel"


def test_cb_model_has_required_methods():
    """Verify the model implements the required continuous batching methods."""
    model_py = PROJECT_ROOT / "model_repo" / "cb_model" / "1" / "model.py"
    cls = load_litapi_from_file(model_py)
    instance = cls()
    instance.setup("cpu")

    assert hasattr(instance, "has_active_requests")
    assert hasattr(instance, "has_capacity")
    assert hasattr(instance, "has_finished")
    assert callable(instance.has_active_requests)
    assert callable(instance.has_capacity)
    assert callable(instance.has_finished)

    # Initially no active requests
    assert instance.has_active_requests() is False
    assert instance.has_capacity() is True


def test_cb_model_predict_and_finish():
    """Verify the model's predict and has_finished logic."""
    model_py = PROJECT_ROOT / "model_repo" / "cb_model" / "1" / "model.py"
    cls = load_litapi_from_file(model_py)
    instance = cls()
    instance.setup("cpu")
    instance.max_batch_size = 4

    # Simulate two active sequences
    instance._active = {"uid1": {}, "uid2": {}}
    inputs = ["hello", "world"]
    generated = [[], []]

    tokens = instance.predict(inputs, generated)
    assert len(tokens) == 2
    assert tokens[0] == "tok_0"
    assert tokens[1] == "tok_0"

    # After 5 tokens, should return EOS
    assert instance.has_finished("uid1", "tok_0", 10) is False
    assert instance.has_finished("uid1", "<EOS>", 10) is True


def test_cb_model_manager_load():
    """Test loading a continuous batching model through ModelManager."""
    repo = PROJECT_ROOT / "model_repo"
    manager = mp.Manager()
    registry = ModelRegistry(manager)
    mm = ModelManager(repo, registry)

    success = mm.load("cb_model", "1")
    assert success is True

    entry = registry.get("cb_model", "1")
    assert entry is not None
    assert entry["status"] == "READY"

    config = entry.get("config", {})
    assert config.get("continuous_batching") is True
    assert config.get("stream") is True
    assert config.get("max_sequence_length") == 10

    mm.unload("cb_model", "1")


def test_cb_forces_single_worker():
    """Verify that continuous batching forces workers_per_device=1."""
    repo = PROJECT_ROOT / "model_repo"
    manager = mp.Manager()
    registry = ModelRegistry(manager)
    mm = ModelManager(repo, registry)

    # Override with workers_per_device=3; should be forced to 1
    override = ModelConfig(
        name="cb_model",
        workers_per_device=3,
    )
    success = mm.load("cb_model", "1", config_override=override)
    assert success is True

    entry = registry.get("cb_model", "1")
    config = entry.get("config", {})
    assert config.get("workers_per_device") == 1

    mm.unload("cb_model", "1")


def test_config_continuous_batching_fields():
    """Verify ModelConfig dataclass accepts new fields."""
    cfg = ModelConfig(
        name="test",
        continuous_batching=True,
        max_sequence_length=4096,
    )
    assert cfg.continuous_batching is True
    assert cfg.max_sequence_length == 4096
