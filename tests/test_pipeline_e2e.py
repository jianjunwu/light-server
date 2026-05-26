"""End-to-end pipeline test: init -> serve -> pack -> serve(.lma) -> unpack -> serve."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_free_port() -> int:
    """Return an available TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_server_config(repo_path: Path, http_port: int, load_models: list[str]) -> str:
    """Generate a minimal server config YAML."""
    model_lines = "".join("  - " + m + "\n" for m in load_models)
    return f"""server:
  host: 127.0.0.1
  http_port: {http_port}
  log_level: warning
  num_api_servers: 1
grpc:
  enabled: false
metrics:
  enabled: false
model_repository:
  path: {repo_path}
  control_mode: explicit
load_models:
{model_lines}
"""


def _wait_for_server(base_url: str, timeout: float = 30.0) -> None:
    """Poll /health until the server is up."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Server did not start within {timeout}s")


def _start_server(config_path: Path) -> subprocess.Popen:
    """Start the light-server in a subprocess."""
    return subprocess.Popen(
        [sys.executable, "-m", "light_server", "serve", "--config", str(config_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(PROJECT_ROOT),
    )


def _stop_server(proc: subprocess.Popen) -> None:
    """Gracefully terminate the server subprocess."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    # Give the OS a moment to free the port
    time.sleep(0.5)


def _test_infer(base_url: str, model_name: str, expected: float) -> None:
    """Send an inference request and assert the result."""
    resp = requests.post(
        f"{base_url}/v2/models/{model_name}/infer",
        json={"input": 5.0},
        timeout=10,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("result") == expected, f"Expected {expected}, got {data}"


def _test_ready(base_url: str, model_name: str) -> None:
    """Check that the model is ready."""
    resp = requests.get(f"{base_url}/v2/models/{model_name}/ready", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["ready"] is True


@pytest.fixture
def pipeline_project(tmp_path: Path) -> Path:
    """Run `light-server init` and return the project root."""
    result = subprocess.run(
        [sys.executable, "-m", "light_server", "init", "demo", "--template", "empty"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    )
    project = tmp_path / "demo"
    assert project.exists(), f"init failed: {result.stderr}"
    return project


def test_full_pipeline(pipeline_project: Path) -> None:
    """Full lifecycle: init -> serve(source) -> pack -> serve(.lma) -> unpack -> serve(unpacked)."""

    # ── Step 1: serve from source model_repo ───────────────────────────────
    port1 = _get_free_port()
    repo_src = pipeline_project / "model_repo"
    config = pipeline_project / "server.yaml"
    config.write_text(_make_server_config(repo_src, port1, ["my_model"]))

    proc = _start_server(config)
    try:
        base = f"http://127.0.0.1:{port1}"
        _wait_for_server(base)
        _test_ready(base, "my_model")
        _test_infer(base, "my_model", expected=10.0)
    finally:
        _stop_server(proc)

    # ── Step 2: pack ───────────────────────────────────────────────────────
    model_dir = pipeline_project / "model_repo" / "my_model"
    artifacts = pipeline_project / "artifacts"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "light_server",
            "pack",
            str(model_dir),
            "--version",
            "1.0.0",
            "-o",
            str(artifacts),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    lma_files = list(artifacts.glob("*.lma"))
    assert len(lma_files) == 1
    artifact = lma_files[0]

    # ── Step 3: serve from .lma artifact ───────────────────────────────────
    port2 = _get_free_port()
    lma_repo = pipeline_project / "lma_repo"
    lma_repo.mkdir()
    (lma_repo / artifact.name).write_bytes(artifact.read_bytes())
    config.write_text(_make_server_config(lma_repo, port2, ["my_model"]))

    proc = _start_server(config)
    try:
        base = f"http://127.0.0.1:{port2}"
        _wait_for_server(base)
        _test_ready(base, "my_model")
        _test_infer(base, "my_model", expected=10.0)
    finally:
        _stop_server(proc)

    # ── Step 4: unpack ─────────────────────────────────────────────────────
    unpacked = pipeline_project / "unpacked_repo"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "light_server",
            "unpack",
            str(artifact),
            "--to",
            str(unpacked),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert (unpacked / "my_model" / "1" / "model.py").exists()

    # ── Step 5: serve from unpacked directory ──────────────────────────────
    port3 = _get_free_port()
    config.write_text(_make_server_config(unpacked, port3, ["my_model"]))

    proc = _start_server(config)
    try:
        base = f"http://127.0.0.1:{port3}"
        _wait_for_server(base)
        _test_ready(base, "my_model")
        _test_infer(base, "my_model", expected=10.0)
    finally:
        _stop_server(proc)
