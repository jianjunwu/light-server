import tempfile
from pathlib import Path

import yaml

from light_server.config import Config, FeaturesConfig, load_config, load_orchestration


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
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        f.flush()
        config = load_config(f.name)

    assert config.server.http_port == 9000
    assert config.grpc.enabled is True
    assert config.grpc.max_workers == 20
    assert config.model_repository.path == "/tmp/models"


def test_load_orchestration():
    """Load orchestration.yaml with model loading strategies."""
    data = {
        "control_mode": "poll",
        "poll_interval": 10,
        "load_models": ["model1", "model2"],
        "models": [
            {
                "name": "model1",
                "load_policy": "explicit",
                "versions_to_load": ["1"],
                "default_version": "1",
            }
        ],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        f.flush()
        orch = load_orchestration(f.name)

    assert orch.control_mode == "poll"
    assert orch.poll_interval == 10
    assert orch.load_models == ["model1", "model2"]
    assert len(orch.models) == 1
    assert orch.models[0].name == "model1"
    assert orch.models[0].load_policy == "explicit"
    assert orch.models[0].versions_to_load == ["1"]
    assert orch.models[0].default_version == "1"


def test_server_config_no_num_api_servers():
    """num_api_servers was removed from ServerConfig."""
    data = {"server": {"num_api_servers": 5}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        f.flush()
        config = load_config(f.name)

    # Field should be ignored, default http_workers should be None
    assert not hasattr(config.server, "num_api_servers")


def test_server_config_no_devices_workers():
    """devices and workers_per_device were removed from ServerConfig."""
    data = {"server": {"devices": 2, "workers_per_device": 4}}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        f.flush()
        config = load_config(f.name)

    assert not hasattr(config.server, "devices")
    assert not hasattr(config.server, "workers_per_device")
