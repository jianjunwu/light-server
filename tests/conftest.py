import shutil
from pathlib import Path

import pytest


@pytest.fixture
def sample_config():
    return {
        "server": {
            "http_port": 18000,
            "grpc_port": 18001,
            "metrics_port": 18002,
            "host": "127.0.0.1",
            "num_api_servers": 1,
        },
        "grpc": {"enabled": False},
        "metrics": {"enabled": False},
        "model_repository": {
            "path": "./model_repo",
            "control_mode": "explicit",
        },
        "load_models": ["test_model"],
    }


@pytest.fixture
def isolated_model_repo(tmp_path):
    """Create an isolated copy of the model repository for tests.

    Returns the path to the copied model_repo directory. Tests that modify
    model files or configs should use this fixture to avoid polluting the
    real model_repo and interfering with other tests.
    """
    src = Path(__file__).resolve().parent.parent / "model_repo"
    dst = tmp_path / "model_repo"
    shutil.copytree(
        src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    return dst
