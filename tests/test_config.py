import tempfile
from pathlib import Path

import yaml

from light_server.config import Config, load_config


def test_load_config_minimal():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"server": {"http_port": 9000}}, f)
        f.flush()
        config = load_config(f.name)

    assert config.server.http_port == 9000
    assert config.server.grpc_port == 8001


def test_load_config_full():
    data = {
        "server": {
            "http_port": 9000,
            "grpc_port": 9001,
            "metrics_port": 9002,
            "host": "127.0.0.1",
        },
        "grpc": {"enabled": True, "max_workers": 20},
        "metrics": {"enabled": True},
        "model_repository": {
            "path": "/tmp/models",
            "control_mode": "poll",
            "poll_interval": 10,
        },
        "load_models": ["model1", "model2"],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        f.flush()
        config = load_config(f.name)

    assert config.server.http_port == 9000
    assert config.grpc.enabled is True
    assert config.grpc.max_workers == 20
    assert config.model_repository.control_mode == "poll"
    assert config.load_models == ["model1", "model2"]
