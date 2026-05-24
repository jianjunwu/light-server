"""Test graceful shutdown on SIGINT (Ctrl+C)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_free_port() -> int:
    """Return an available TCP port on 127.0.0.1."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_server_config(repo_path: Path, http_port: int, load_models: list[str] | None = None) -> str:
    """Generate a server config YAML."""
    load_block = ""
    if load_models is not None:
        if load_models:
            load_block = "load_models:\n" + "\n".join(f"- {m}" for m in load_models)
        else:
            load_block = "load_models: []"
    return f"""
grpc:
  enabled: false
metrics:
  enabled: false
{load_block}
model_repository:
  control_mode: explicit
  path: {repo_path}
server:
  host: 127.0.0.1
  http_port: {http_port}
  log_level: warning
"""


def _start_server(repo_path: Path, http_port: int, load_models: list[str] | None = None):
    """Start the server subprocess and return (proc, temp_config)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(_make_server_config(repo_path, http_port, load_models))
        temp_config = f.name

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "light_server",
            "serve",
            "--config",
            temp_config,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    return proc, temp_config


def _wait_for_ready(http_port: int, timeout: float = 15.0) -> None:
    """Poll health endpoint until server is ready."""
    base = f"http://127.0.0.1:{http_port}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{base}/health", timeout=2)
            if resp.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(0.2)
    pytest.fail("Server did not become ready")


def _cleanup(proc: subprocess.Popen, temp_config: str) -> None:
    """Terminate process and clean up temp file."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    try:
        Path(temp_config).unlink()
    except OSError:
        pass


def test_sigint_with_loaded_model(isolated_model_repo):
    """Send SIGINT to a running server with loaded model."""
    http_port = _get_free_port()
    proc, temp_config = _start_server(isolated_model_repo, http_port, ["test_model"])

    try:
        _wait_for_ready(http_port)
        os.kill(proc.pid, signal.SIGINT)
        proc.wait(timeout=10)
        assert proc.returncode == 0, f"Server exited with code {proc.returncode}"
    finally:
        _cleanup(proc, temp_config)


def test_sigint_with_active_request(isolated_model_repo):
    """Send SIGINT while a request is in flight."""
    http_port = _get_free_port()
    proc, temp_config = _start_server(isolated_model_repo, http_port, ["test_model"])

    try:
        _wait_for_ready(http_port)
        base = f"http://127.0.0.1:{http_port}"

        # Send a request in a background thread
        import threading

        def do_request():
            try:
                requests.post(
                    f"{base}/v2/models/test_model/infer",
                    json={"input": 4.0},
                    timeout=30,
                )
            except Exception:
                pass

        t = threading.Thread(target=do_request)
        t.start()
        time.sleep(0.3)  # let request be in flight

        os.kill(proc.pid, signal.SIGINT)
        proc.wait(timeout=10)
        assert proc.returncode == 0, f"Server exited with code {proc.returncode}"
        t.join(timeout=5)
    finally:
        _cleanup(proc, temp_config)


def test_double_sigint_shuts_down(isolated_model_repo):
    """Send two SIGINTs rapidly and verify server exits."""
    http_port = _get_free_port()
    proc, temp_config = _start_server(isolated_model_repo, http_port, ["test_model"])

    try:
        _wait_for_ready(http_port)
        os.kill(proc.pid, signal.SIGINT)
        time.sleep(0.1)
        os.kill(proc.pid, signal.SIGINT)
        proc.wait(timeout=10)
        assert proc.returncode in (0, 1), f"Server exited with code {proc.returncode}"
    finally:
        stdout_data = proc.stdout.read() if proc.stdout else ""
        if proc.returncode not in (0, 1) and stdout_data:
            print(f"Server output:\n{stdout_data}")
        _cleanup(proc, temp_config)
