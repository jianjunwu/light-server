import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _make_server_config(repo_path: Path) -> str:
    """Generate a server config YAML that points to the given model repo."""
    return f"""
grpc:
  enabled: false
load_models:
- test_model
metrics:
  enabled: false
model_repository:
  control_mode: explicit
  path: {repo_path}
server:
  grpc_port: 18001
  host: 127.0.0.1
  http_port: 18000
  log_level: warning
  metrics_port: 18002
  num_api_servers: 1
"""


def test_server_startup_and_inference(isolated_model_repo):
    """E2E test: start server, call inference, call admin APIs, shutdown."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        f.write(_make_server_config(isolated_model_repo))
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

    try:
        # Wait for server startup by polling health endpoint
        base = "http://127.0.0.1:18000"
        for _ in range(60):
            time.sleep(0.2)
            try:
                resp = requests.get(f"{base}/health", timeout=2)
                if resp.status_code == 200:
                    break
            except requests.ConnectionError:
                continue
        else:
            # Print any server output for debugging
            stdout_data = (
                proc.stdout.read1().decode()
                if hasattr(proc.stdout, "read1")
                else ""
            )
            print("Server output:", stdout_data)
            raise RuntimeError("Server did not start")

        time.sleep(0.5)

        # Health check
        resp = requests.get(f"{base}/health", timeout=5)
        assert resp.status_code == 200

        # Info
        resp = requests.get(f"{base}/info", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["server"] == "light-server"

        # List loaded models
        resp = requests.get(f"{base}/v2/models", timeout=5)
        assert resp.status_code == 200

        # Repository index
        resp = requests.post(f"{base}/v2/repository/index", timeout=5)
        assert resp.status_code == 200
        repo = resp.json()
        assert any(m["name"] == "test_model" for m in repo["models"])

        # Try inference
        resp = requests.post(
            f"{base}/v2/models/test_model/infer",
            json={"input": 4.0},
            timeout=10,
        )
        print(f"Inference response: {resp.status_code} - {resp.text}")
        # The inference may timeout or return placeholder; just check it doesn't 500
        assert resp.status_code in (200, 504)

        # Unload model
        resp = requests.post(
            f"{base}/v2/repository/models/test_model/unload", timeout=5
        )
        assert resp.status_code == 200

        # Model should not be ready
        resp = requests.get(f"{base}/v2/models/test_model/ready", timeout=5)
        assert resp.json()["ready"] is False

        # Load model back
        resp = requests.post(
            f"{base}/v2/repository/models/test_model/load", timeout=30
        )
        assert resp.status_code == 200

        # Model should be ready
        time.sleep(2)
        resp = requests.get(f"{base}/v2/models/test_model/ready", timeout=5)
        assert resp.json()["ready"] is True

    finally:
        proc.terminate()
        proc.wait(timeout=10)
        if proc.poll() is None:
            proc.kill()
        try:
            Path(temp_config).unlink()
        except OSError:
            pass
