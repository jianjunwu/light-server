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
