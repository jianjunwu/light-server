import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


def _get_free_port() -> int:
    """Return an available TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_config(repo_path: Path, http_port: int) -> str:
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
  host: 127.0.0.1
  http_port: {http_port}
  log_level: warning
  num_api_servers: 1
"""


def _start_server(repo_path: Path):
    """Start light-server with retry. Returns (proc, temp_config_path, base_url)."""
    for attempt in range(2):
        http_port = _get_free_port()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(_make_config(repo_path, http_port))
            temp_config = f.name

        proc = subprocess.Popen(
            [sys.executable, "-m", "light_server", "serve", "--config", temp_config],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )

        base = f"http://127.0.0.1:{http_port}"
        import requests

        for _ in range(60):
            time.sleep(0.3)
            try:
                resp = requests.get(f"{base}/health", timeout=2)
                if resp.status_code == 200:
                    return proc, temp_config, base
            except requests.ConnectionError:
                continue

        # Startup failed on this port – clean up and retry once
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        Path(temp_config).unlink(missing_ok=True)

    raise RuntimeError("Server did not start after 2 attempts")


def _cleanup(proc, temp_config):
    """Kill the server process group and remove temp config."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    Path(temp_config).unlink(missing_ok=True)


def test_websocket_bidirectional_stream(isolated_model_repo):
    """E2E test: start server with stream_model, connect via WebSocket, send chunks, receive echoes."""
    proc, temp_config, base = _start_server(isolated_model_repo)

    try:
        ws_url = f"ws://127.0.0.1:{base.split(':')[-1]}/v2/models/stream_model/stream"

        time.sleep(0.5)

        # Load the stream model
        import requests
        resp = requests.post(
            f"{base}/v2/repository/models/stream_model/load",
            timeout=10,
        )
        print(f"Load response: {resp.status_code} - {resp.text}")
        assert resp.status_code == 200

        # Wait for model to be ready
        for _ in range(20):
            time.sleep(0.3)
            resp = requests.get(f"{base}/v2/models/stream_model/ready", timeout=5)
            if resp.json().get("ready"):
                break
        else:
            raise RuntimeError("Model did not become ready")

        # Connect via WebSocket and stream
        import websockets

        received = []

        async def run_ws():
            async with websockets.connect(ws_url, proxy=None) as ws:
                for i in range(3):
                    await ws.send(json.dumps({"idx": i, "text": f"hello-{i}"}))
                    await asyncio.sleep(0.2)

                for _ in range(5):
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        received.append(json.loads(msg))
                    except asyncio.TimeoutError:
                        break

                await ws.close()

        asyncio.run(run_ws())

        print(f"Received {len(received)} messages: {received}")
        assert len(received) >= 3, f"Expected at least 3 responses, got {len(received)}"

        for i, msg in enumerate(received[:3]):
            assert "echo" in msg, f"Message {i} missing 'echo' key: {msg}"
            assert msg["echo"]["idx"] == i, f"Message {i} wrong idx: {msg}"

    finally:
        _cleanup(proc, temp_config)


def test_websocket_unloaded_model(isolated_model_repo):
    """E2E test: WebSocket to an unloaded model should be rejected gracefully."""
    proc, temp_config, base = _start_server(isolated_model_repo)

    try:
        ws_url = f"ws://127.0.0.1:{base.split(':')[-1]}/v2/models/stream_model/stream"

        time.sleep(0.3)

        import websockets

        async def run_ws():
            try:
                async with websockets.connect(ws_url, proxy=None) as ws:
                    await ws.send(json.dumps({"text": "hello"}))
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    assert False, f"Expected connection close, got: {msg}"
            except websockets.exceptions.ConnectionClosed as e:
                close_code = getattr(e, "rcvd", e).code if hasattr(getattr(e, "rcvd", e), "code") else e.code
                close_reason = getattr(e, "rcvd", e).reason if hasattr(getattr(e, "rcvd", e), "reason") else e.reason
                assert close_code == 1011, f"Expected 1011, got {close_code}"
                assert "not ready" in close_reason.lower() or "stream_model" in close_reason

        asyncio.run(run_ws())

    finally:
        _cleanup(proc, temp_config)
