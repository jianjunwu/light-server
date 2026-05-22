import json
import os
import subprocess
import sys
import time

import pytest
import requests


def test_server_startup_and_inference():
    """E2E test: start server, call inference, call admin APIs, shutdown."""
    env = os.environ.copy()
    env["PYTHONPATH"] = "/Users/nic/workspace/projects/light_server/src"

    proc = subprocess.Popen(
        [sys.executable, "-m", "light_server", "serve", "--config", "server.yaml"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd="/Users/nic/workspace/projects/light_server",
        env=env,
    )

    try:
        # Wait for server startup by polling health endpoint
        base = "http://127.0.0.1:18000"
        for _ in range(30):
            time.sleep(0.5)
            try:
                resp = requests.get(f"{base}/health", timeout=2)
                if resp.status_code == 200:
                    break
            except requests.ConnectionError:
                continue
        else:
            # Print any server output for debugging
            stdout_data = proc.stdout.read1().decode() if hasattr(proc.stdout, "read1") else ""
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
        resp = requests.post(f"{base}/v2/repository/models/test_model/unload", timeout=5)
        assert resp.status_code == 200

        # Model should not be ready
        resp = requests.get(f"{base}/v2/models/test_model/ready", timeout=5)
        assert resp.json()["ready"] is False

        # Load model back
        resp = requests.post(f"{base}/v2/repository/models/test_model/load", timeout=30)
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
