import tempfile
from pathlib import Path

import yaml

from light_server.config import Config, FeaturesConfig, load_config


def test_features_config_defaults():
    """FeaturesConfig should have sensible defaults."""
    cfg = FeaturesConfig()
    assert cfg.timeline is False
    assert cfg.system_overview is True
    assert cfg.custom_metrics is False
    assert cfg.benchmarks is True
    assert cfg.playground is False
    assert cfg.alerts is True
    assert cfg.version_compare is False


def test_load_config_with_features():
    """Load config with explicit features block."""
    data = {
        "features": {
            "timeline": True,
            "custom_metrics": True,
            "playground": True,
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        f.flush()
        config = load_config(f.name)

    assert config.features.timeline is True
    assert config.features.system_overview is True  # default unchanged
    assert config.features.custom_metrics is True
    assert config.features.playground is True
    assert config.features.benchmarks is True  # default
    assert config.features.alerts is True  # default
    assert config.features.version_compare is False  # default


def test_load_config_minimal():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"server": {"http_port": 9000}}, f)
        f.flush()
        config = load_config(f.name)

    assert config.server.http_port == 9000
    assert config.server.grpc_port == 8001
    assert config.server.transport == "mp"


def test_load_config_transport_zmq():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"server": {"transport": "zmq"}}, f)
        f.flush()
        config = load_config(f.name)

    assert config.server.transport == "zmq"


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
