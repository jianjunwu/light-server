"""Tests for LightServer._load_initial_models with ModelStrategyConfig dataclass."""

from __future__ import annotations

from pathlib import Path

import pytest

from light_server.config import Config, ModelRepositoryConfig, ModelStrategyConfig, OrchestrationConfig, ServerConfig
from light_server.core.server import LightServer


@pytest.fixture
def tmp_model_repo(tmp_path: Path):
    """Create a minimal model repo with one model version."""
    repo = tmp_path / "model_repo"
    model_dir = repo / "my_model" / "1"
    model_dir.mkdir(parents=True)
    (model_dir / "model.py").write_text(
        "from litserve import LitAPI\n\n"
        "class MyAPI(LitAPI):\n"
        "    def setup(self, device):\n"
        "        pass\n"
        "    def decode_request(self, request):\n"
        "        return request\n"
        "    def predict(self, x):\n"
        "        return x\n"
        "    def encode_response(self, output):\n"
        "        return output\n"
    )
    return repo


def test_load_initial_models_with_strategy_dataclass(tmp_model_repo: Path):
    """_load_initial_models should handle ModelStrategyConfig dataclass, not dict.

    Regression test for: AttributeError: 'ModelStrategyConfig' object has no attribute 'get'
    """
    config = Config(
        server=ServerConfig(
            http_port=18000,
            host="127.0.0.1",
            log_level="warning",
        ),
        model_repository=ModelRepositoryConfig(path=str(tmp_model_repo)),
        orchestration=OrchestrationConfig(
            control_mode="explicit",
            load_models=["my_model"],
            models=[
                ModelStrategyConfig(
                    name="my_model",
                    load_policy="all",
                    versions_to_load=["1"],
                    default_version="1",
                ),
            ],
        ),
    )

    server = LightServer(config)
    # This should NOT raise AttributeError: 'ModelStrategyConfig' object has no attribute 'get'
    server._load_initial_models()

    # Verify the model was loaded
    loaded = server.registry.list_loaded()
    assert any(m["name"] == "my_model" and m["version"] == "1" for m in loaded)
