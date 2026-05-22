"""Simple unit tests that don't require subprocess."""

from light_server.config import Config, GrpcConfig, MetricsConfig, ModelConfig, ModelRepositoryConfig, ServerConfig
from light_server.core.loader import load_litapi_from_file
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry

from pathlib import Path


def test_load_litapi():
    model_py = Path(__file__).parent.parent / "model_repo" / "test_model" / "1" / "model.py"
    cls = load_litapi_from_file(model_py)
    assert cls.__name__ == "TestModel"


def test_model_registry():
    import multiprocessing as mp
    manager = mp.Manager()
    registry = ModelRegistry(manager)
    registry.register("test", "1", {"max_batch_size": 8})
    registry.set_status("test", "READY")
    assert registry.is_ready("test")
    assert not registry.is_ready("missing")


def test_model_manager_list_repo():
    repo = Path(__file__).parent.parent / "model_repo"
    import multiprocessing as mp
    manager = mp.Manager()
    registry = ModelRegistry(manager)
    mm = ModelManager(repo, registry)
    models = mm.list_repository()
    assert any(m["name"] == "test_model" for m in models)
