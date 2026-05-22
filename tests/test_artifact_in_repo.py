"""Tests for .lma artifacts coexisting with plain models in model_repo."""

from __future__ import annotations

from pathlib import Path

import pytest

from light_server.artifact.packer import ModelPacker
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry


MODEL_PY_CONTENT = '''
import light_server as ls

class MyAPI(ls.LitAPI):
    def setup(self, device):
        pass
    def decode_request(self, request, **kwargs):
        return request["input"]
    def predict(self, x, **kwargs):
        return x * 2
    def encode_response(self, output, **kwargs):
        return {"output": output}
'''


@pytest.fixture
def mixed_repo(tmp_path: Path) -> Path:
    """Create a model_repo with both plain models and .lma artifacts."""
    repo = tmp_path / "model_repo"
    repo.mkdir()

    # Plain model: plain_model/1/
    plain_dir = repo / "plain_model" / "1"
    plain_dir.mkdir(parents=True)
    (plain_dir / "model.py").write_text(MODEL_PY_CONTENT)
    (plain_dir / "config.yaml").write_text("max_batch_size: 2\n")

    # Artifact model: pack test_model into .lma and place in repo
    artifact_model_dir = tmp_path / "test_model"
    v1 = artifact_model_dir / "1"
    v1.mkdir(parents=True)
    (v1 / "model.py").write_text(MODEL_PY_CONTENT)
    (v1 / "config.yaml").write_text("max_batch_size: 4\n")

    packer = ModelPacker(model_dir=artifact_model_dir, version="1.0.0")
    packer.pack(repo)
    # packer.pack(repo) creates repo/test_model-1.0.0-{build_id}.lma

    return repo


def test_list_repository_mixed_plain_and_artifact(mixed_repo: Path):
    registry = ModelRegistry()
    manager = ModelManager(repo_path=mixed_repo, registry=registry)
    models = manager.list_repository()

    names = {m["name"] for m in models}
    assert "plain_model" in names
    assert "test_model" in names


def test_load_artifact_model_from_repo(mixed_repo: Path):
    registry = ModelRegistry()
    manager = ModelManager(repo_path=mixed_repo, registry=registry)
    manager.list_repository()  # populate _artifact_model_paths

    success = manager.load("test_model", version="1")
    assert success is True
    assert registry.is_ready("test_model", "1")


def test_load_plain_model_from_repo(mixed_repo: Path):
    registry = ModelRegistry()
    manager = ModelManager(repo_path=mixed_repo, registry=registry)
    manager.list_repository()  # populate _artifact_model_paths

    success = manager.load("plain_model", version="1")
    assert success is True
    assert registry.is_ready("plain_model", "1")


def test_artifact_model_hot_reload_path(mixed_repo: Path):
    """Artifact models extracted to cache should have valid paths for hot reload."""
    registry = ModelRegistry()
    manager = ModelManager(repo_path=mixed_repo, registry=registry)
    manager.list_repository()

    # Verify the artifact model base path is cached
    assert "test_model" in manager._artifact_model_paths
    cached_base = manager._artifact_model_paths["test_model"]
    assert (cached_base / "1" / "model.py").exists()
