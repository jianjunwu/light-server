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
    registry.set_status("test", "1", "READY")
    assert registry.is_ready("test", "1")
    assert not registry.is_ready("missing")

    # Multi-version support
    registry.register("test", "2", {"max_batch_size": 16})
    registry.set_status("test", "2", "READY")
    registry.activate_version("test", "1")
    assert registry.get_active_version("test") == "1"
    assert registry.is_ready("test")  # uses active version
    registry.activate_version("test", "2")
    assert registry.get_active_version("test") == "2"
    versions = registry.list_versions("test")
    assert len(versions) == 2
    for v in versions:
        assert v["model_type"] == "litapi"
    assert versions[0]["version"] in ("1", "2")
    assert versions[1]["version"] in ("1", "2")


def test_model_manager_list_repo():
    repo = Path(__file__).parent.parent / "model_repo"
    import multiprocessing as mp
    manager = mp.Manager()
    registry = ModelRegistry(manager)
    mm = ModelManager(repo, registry)
    models = mm.list_repository()
    assert any(m["name"] == "test_model" for m in models)
