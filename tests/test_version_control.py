"""Tests for multi-version model control and generic file hot reload."""

import os
import time
from pathlib import Path

import pytest

from light_server.config import ModelConfig
from light_server.core.model_manager import ModelManager
from light_server.core.registry import ModelRegistry
from light_server.core.server import LightServer
from litserve.transport.factory import TransportConfig, create_transport_from_config
from litserve.utils import LitAPIStatus


def _create_test_env(repo_path: Path):
    """Create manager, registry, transport, and model manager for tests."""
    import multiprocessing as mp
    manager = mp.Manager()
    registry = ModelRegistry(manager)

    transport_config = TransportConfig(transport_type="mp", num_consumers=1)
    transport_config.manager = manager
    transport = create_transport_from_config(transport_config)

    mm = ModelManager(repo_path, registry, transport=transport)
    return manager, registry, transport, mm


def _write_orchestration(repo_path: Path, content: str) -> None:
    """Helper to overwrite model_repo/orchestration.yaml."""
    path = repo_path / "orchestration.yaml"
    path.write_text(content)


def _restore_orchestration(repo_path: Path) -> None:
    """Restore default model_repo/orchestration.yaml."""
    _write_orchestration(
        repo_path,
        'control_mode: explicit\n'
        'poll_interval: 5\n'
        'load_models:\n'
        '  - test_model\n'
        'models:\n'
        '  - name: test_model\n'
        '    load_policy: explicit\n'
        '    versions_to_load:\n'
        '      - "1"\n'
        '      - "2"\n'
        '    default_version: "1"\n'
        '  - name: stream_model\n'
        '    load_policy: all\n'
        '  - name: my_ensemble\n'
        '    load_policy: all\n'
        '  - name: cb_model\n'
        '    load_policy: all\n',
    )


def test_load_multiple_versions(isolated_model_repo):
    """Load v1 and v2 of the same model simultaneously."""
    _m, registry, transport, mm = _create_test_env(isolated_model_repo)

    assert mm.load("test_model", version="1")
    assert mm.load("test_model", version="2")

    # Wait for workers to be ready
    time.sleep(2)

    assert registry.is_ready("test_model", "1")
    assert registry.is_ready("test_model", "2")

    # Active version should be auto-set to first loaded
    assert registry.get_active_version("test_model") == "1"

    # Infer v1: should return x**2 = 16
    uid1 = mm.infer("test_model", {"input": 4.0}, version="1", response_queue_id=0)
    result1 = transport._queues[0].get(timeout=10)
    assert result1[1][0] == {"output": 16.0}

    # Infer v2: should return x**3 = 64
    uid2 = mm.infer("test_model", {"input": 4.0}, version="2", response_queue_id=0)
    result2 = transport._queues[0].get(timeout=10)
    assert result2[1][0] == {"output": 64.0}

    mm.unload("test_model", version="1")
    mm.unload("test_model", version="2")


def test_active_version_switching(isolated_model_repo):
    """Switch active version and verify default routing follows it."""
    _m, registry, transport, mm = _create_test_env(isolated_model_repo)

    assert mm.load("test_model", version="1")
    assert mm.load("test_model", version="2")
    time.sleep(2)

    # Default route goes to v1 (first loaded)
    uid = mm.infer("test_model", {"input": 3.0}, response_queue_id=0)
    result = transport._queues[0].get(timeout=10)
    assert result[1][0] == {"output": 9.0}  # 3**2

    # Switch active to v2
    assert mm.activate("test_model", "2")
    assert registry.get_active_version("test_model") == "2"

    # Default route now goes to v2
    uid = mm.infer("test_model", {"input": 3.0}, response_queue_id=0)
    result = transport._queues[0].get(timeout=10)
    assert result[1][0] == {"output": 27.0}  # 3**3

    mm.unload("test_model")


def test_unload_specific_version(isolated_model_repo):
    """Unload one version while keeping another loaded."""
    _m, registry, transport, mm = _create_test_env(isolated_model_repo)

    assert mm.load("test_model", version="1")
    assert mm.load("test_model", version="2")
    time.sleep(2)

    # Unload v1 only
    assert mm.unload("test_model", version="1")
    assert not registry.is_ready("test_model", "1")
    assert registry.is_ready("test_model", "2")

    # Active version should have switched to v2
    assert registry.get_active_version("test_model") == "2"

    # v2 should still be inferable
    uid = mm.infer("test_model", {"input": 2.0}, response_queue_id=0)
    result = transport._queues[0].get(timeout=10)
    assert result[1][0] == {"output": 8.0}

    mm.unload("test_model")


def test_fallback_py_hot_reload(isolated_model_repo):
    """Modify a .py file and verify fallback auto-reload works (v1 has no on_file_changed)."""
    _m, registry, transport, mm = _create_test_env(isolated_model_repo)

    assert mm.load("test_model", version="1")
    time.sleep(2)

    # Verify initial behavior
    uid = mm.infer("test_model", {"input": 5.0}, version="1", response_queue_id=0)
    result = transport._queues[0].get(timeout=10)
    assert result[1][0] == {"output": 25.0}

    # Modify utils.py in v1 (isolated copy)
    utils_path = isolated_model_repo / "test_model" / "1" / "utils.py"
    original = utils_path.read_text()
    try:
        utils_path.write_text(original.replace("x ** 2", "x ** 2 + 1"))

        # Wait for watcher to detect and reload
        time.sleep(1.5)

        # Verify new behavior
        uid = mm.infer("test_model", {"input": 5.0}, version="1", response_queue_id=0)
        result = transport._queues[0].get(timeout=10)
        assert result[1][0] == {"output": 26.0}  # 5**2 + 1
    finally:
        utils_path.write_text(original)

    mm.unload("test_model", version="1")


def test_on_file_changed_callback(isolated_model_repo):
    """v2 implements on_file_changed — verify it suppresses fallback reload."""
    _m, registry, transport, mm = _create_test_env(isolated_model_repo)

    assert mm.load("test_model", version="2")
    time.sleep(2)

    # Verify initial behavior
    uid = mm.infer("test_model", {"input": 5.0}, version="2", response_queue_id=0)
    result = transport._queues[0].get(timeout=10)
    assert result[1][0] == {"output": 125.0}

    # Modify utils.py in v2 (isolated copy)
    utils_path = isolated_model_repo / "test_model" / "2" / "utils.py"
    original = utils_path.read_text()
    try:
        utils_path.write_text(original.replace("x ** 3", "x ** 3 + 1"))

        # Wait for watcher to detect
        time.sleep(1.5)

        # Because on_file_changed returns "handled", fallback reload is suppressed
        # so utils.py should NOT have been reloaded automatically
        uid = mm.infer("test_model", {"input": 5.0}, version="2", response_queue_id=0)
        result = transport._queues[0].get(timeout=10)
        # Should still be original because callback suppressed reload
        assert result[1][0] == {"output": 125.0}
    finally:
        utils_path.write_text(original)

    mm.unload("test_model", version="2")


def test_orchestration_read(isolated_model_repo):
    """Verify get_orchestration reads orchestration.yaml correctly."""
    _m, _r, _t, mm = _create_test_env(isolated_model_repo)
    orch = mm.get_orchestration()
    assert orch["control_mode"] == "explicit"
    assert orch["load_models"] == ["test_model"]
    test_model = next(m for m in orch["models"] if m["name"] == "test_model")
    assert test_model["default_version"] == "1"
    assert test_model["load_policy"] == "explicit"
    assert test_model["versions_to_load"] == ["1", "2"]


def test_orchestration_default_version(isolated_model_repo):
    """default_version is activated even when another version loads first."""
    _write_orchestration(
        isolated_model_repo,
        'control_mode: explicit\n'
        'poll_interval: 5\n'
        'load_models:\n'
        '  - test_model\n'
        'models:\n'
        '  - name: test_model\n'
        '    load_policy: all\n'
        '    default_version: "2"\n'
        '  - name: stream_model\n'
        '    load_policy: all\n'
        '  - name: my_ensemble\n'
        '    load_policy: all\n'
        '  - name: cb_model\n'
        '    load_policy: all\n',
    )
    try:
        _m, registry, _t, mm = _create_test_env(isolated_model_repo)
        # Load v1 first
        assert mm.load("test_model", version="1")
        time.sleep(2)
        # default_version is 2, but it's not loaded yet, so active should be None
        assert registry.get_active_version("test_model") is None

        # Now load v2
        assert mm.load("test_model", version="2")
        time.sleep(2)
        # v2 matches default_version, so it should be activated
        assert registry.get_active_version("test_model") == "2"

        mm.unload("test_model")
    finally:
        _restore_orchestration(isolated_model_repo)


def test_orchestration_max_loaded_versions(isolated_model_repo):
    """Loading beyond max_loaded_versions evicts the oldest version."""
    _write_orchestration(
        isolated_model_repo,
        'control_mode: explicit\n'
        'poll_interval: 5\n'
        'load_models:\n'
        '  - test_model\n'
        'models:\n'
        '  - name: test_model\n'
        '    load_policy: all\n'
        '    default_version: "1"\n'
        '    max_loaded_versions: 1\n'
        '  - name: stream_model\n'
        '    load_policy: all\n'
        '  - name: my_ensemble\n'
        '    load_policy: all\n'
        '  - name: cb_model\n'
        '    load_policy: all\n',
    )
    try:
        _m, registry, _t, mm = _create_test_env(isolated_model_repo)
        assert mm.load("test_model", version="1")
        time.sleep(2)
        assert registry.is_ready("test_model", "1")

        # Load v2: should trigger eviction of v1
        assert mm.load("test_model", version="2")
        time.sleep(2)
        assert not registry.is_ready("test_model", "1")
        assert registry.is_ready("test_model", "2")

        mm.unload("test_model")
    finally:
        _restore_orchestration(isolated_model_repo)


def test_reload_model(isolated_model_repo):
    """Reload a model version and verify it works."""
    _m, registry, transport, mm = _create_test_env(isolated_model_repo)

    assert mm.load("test_model", version="1")
    time.sleep(2)
    assert registry.is_ready("test_model", "1")

    # Verify initial behavior
    uid = mm.infer("test_model", {"input": 5.0}, version="1", response_queue_id=0)
    result = transport._queues[0].get(timeout=10)
    assert result[1][0] == {"output": 25.0}

    # Reload
    assert mm.reload("test_model", version="1")
    time.sleep(2)
    assert registry.is_ready("test_model", "1")

    # Verify still works after reload
    uid = mm.infer("test_model", {"input": 5.0}, version="1", response_queue_id=0)
    result = transport._queues[0].get(timeout=10)
    assert result[1][0] == {"output": 25.0}

    mm.unload("test_model", version="1")


def test_delete_version(isolated_model_repo):
    """Delete a model version from the repository."""
    _m, registry, transport, mm = _create_test_env(isolated_model_repo)

    # Load v1 and v2
    assert mm.load("test_model", version="1")
    assert mm.load("test_model", version="2")
    time.sleep(2)

    # Verify both exist
    assert (isolated_model_repo / "test_model" / "1").exists()
    assert (isolated_model_repo / "test_model" / "2").exists()

    # Delete v1
    assert mm.delete_version("test_model", version="1")
    assert not (isolated_model_repo / "test_model" / "1").exists()
    assert not registry.is_ready("test_model", "1")
    assert registry.is_ready("test_model", "2")

    # Delete v2
    assert mm.delete_version("test_model", version="2")
    assert not (isolated_model_repo / "test_model" / "2").exists()

    mm.unload("test_model")


def test_version_config_read_write(isolated_model_repo):
    """Read and write version-level config.yaml."""
    _m, _r, _t, mm = _create_test_env(isolated_model_repo)

    # Read existing config
    cfg = mm.get_version_config("test_model", "1")
    assert cfg.get("hot_reload") is True
    assert "*.py" in cfg.get("hot_reload_patterns", [])

    # Write new config
    new_cfg = {"max_batch_size": 16, "batch_timeout": 0.05}
    assert mm.set_version_config("test_model", "1", new_cfg)

    # Read back
    cfg = mm.get_version_config("test_model", "1")
    assert cfg["max_batch_size"] == 16
    assert cfg["batch_timeout"] == 0.05


def test_orchestration_read_write(isolated_model_repo):
    """Read and write model_repo/orchestration.yaml."""
    _m, _r, _t, mm = _create_test_env(isolated_model_repo)

    # Read existing orchestration
    orch = mm.get_orchestration()
    assert orch["control_mode"] == "explicit"

    # Write new orchestration
    new_orch = {
        "control_mode": "poll",
        "poll_interval": 10,
        "load_models": ["test_model"],
        "models": [
            {"name": "test_model", "load_policy": "all", "default_version": "2"}
        ],
    }
    assert mm.set_orchestration(new_orch)

    # Read back
    orch = mm.get_orchestration()
    assert orch["control_mode"] == "poll"
    assert orch["poll_interval"] == 10
    test_model = next(m for m in orch["models"] if m["name"] == "test_model")
    assert test_model["default_version"] == "2"
    assert test_model["load_policy"] == "all"
