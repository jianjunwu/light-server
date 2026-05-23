import asyncio
import json
import os
import subprocess
import sys
import time

import pytest


def test_websocket_bidirectional_stream():
    """E2E test: start server with stream_model, connect via WebSocket, send chunks, receive echoes."""
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
        base = "http://127.0.0.1:18000"
        ws_url = "ws://127.0.0.1:18000/v2/models/stream_model/stream"

        # Wait for server startup
        import requests
        for _ in range(30):
            time.sleep(0.5)
            try:
                resp = requests.get(f"{base}/health", timeout=2)
                if resp.status_code == 200:
                    break
            except requests.ConnectionError:
                continue
        else:
            stdout_data = proc.stdout.read1().decode() if hasattr(proc.stdout, "read1") else ""
            print("Server output:", stdout_data)
            raise RuntimeError("Server did not start")

        time.sleep(0.5)

        # Load the stream model
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
            # Disable proxy for local connection
            async with websockets.connect(ws_url, proxy=None) as ws:
                # Send a few chunks
                for i in range(3):
                    await ws.send(json.dumps({"idx": i, "text": f"hello-{i}"}))
                    # Small delay to let worker process
                    await asyncio.sleep(0.2)

                # Wait for all responses
                for _ in range(5):
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        received.append(json.loads(msg))
                    except asyncio.TimeoutError:
                        break

                # Close gracefully
                await ws.close()

        asyncio.run(run_ws())

        print(f"Received {len(received)} messages: {received}")
        assert len(received) >= 3, f"Expected at least 3 responses, got {len(received)}"

        for i, msg in enumerate(received[:3]):
            assert "echo" in msg, f"Message {i} missing 'echo' key: {msg}"
            assert msg["echo"]["idx"] == i, f"Message {i} wrong idx: {msg}"

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_websocket_unloaded_model():
    """E2E test: WebSocket to an unloaded model should be rejected gracefully."""
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
        base = "http://127.0.0.1:18000"
        ws_url = "ws://127.0.0.1:18000/v2/models/stream_model/stream"

        import requests
        for _ in range(30):
            time.sleep(0.5)
            try:
                resp = requests.get(f"{base}/health", timeout=2)
                if resp.status_code == 200:
                    break
            except requests.ConnectionError:
                continue
        else:
            raise RuntimeError("Server did not start")

        # stream_model is NOT loaded in this test
        import websockets

        async def run_ws():
            try:
                async with websockets.connect(ws_url, proxy=None) as ws:
                    await ws.send(json.dumps({"text": "hello"}))
                    # Should not reach here; server closes connection
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    assert False, f"Expected connection close, got: {msg}"
            except websockets.exceptions.ConnectionClosed as e:
                # Server should close with an error code
                # websockets 13.1+ uses rcvd.code/rcvd.reason
                close_code = getattr(e, "rcvd", e).code if hasattr(getattr(e, "rcvd", e), "code") else e.code
                close_reason = getattr(e, "rcvd", e).reason if hasattr(getattr(e, "rcvd", e), "reason") else e.reason
                assert close_code == 1011, f"Expected 1011, got {close_code}"
                assert "not ready" in close_reason.lower() or "stream_model" in close_reason

        asyncio.run(run_ws())

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
