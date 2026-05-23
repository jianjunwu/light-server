import json
import os
import subprocess
import sys
import time

import pytest


@pytest.fixture
def grpc_port():
    return 18001


def test_grpc_bidirectional_stream():
    """E2E test: start server with gRPC enabled, connect via BidirectionalStream."""
    env = os.environ.copy()
    env["PYTHONPATH"] = "/Users/nic/workspace/projects/light_server/src"

    # Use a temporary config with gRPC enabled
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("""
grpc:
  enabled: true
  max_workers: 10
load_models:
- test_model
metrics:
  enabled: false
model_repository:
  control_mode: explicit
  path: ./model_repo
server:
  grpc_port: 18001
  host: 127.0.0.1
  http_port: 18000
  log_level: warning
  metrics_port: 18002
  num_api_servers: 1
""")
        temp_config = f.name

    proc = subprocess.Popen(
        [sys.executable, "-m", "light_server", "serve", "--config", temp_config],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd="/Users/nic/workspace/projects/light_server",
        env=env,
    )

    try:
        base = "http://127.0.0.1:18000"
        grpc_target = "127.0.0.1:18001"

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

        for _ in range(20):
            time.sleep(0.3)
            resp = requests.get(f"{base}/v2/models/stream_model/ready", timeout=5)
            if resp.json().get("ready"):
                break
        else:
            raise RuntimeError("Model did not become ready")

        import grpc
        from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

        channel = grpc.insecure_channel(grpc_target)
        stub = litserve_pb2_grpc.InferenceStub(channel)

        def request_generator():
            # First chunk carries metadata
            meta = json.dumps({"model_name": "stream_model", "version": "1"})
            yield litserve_pb2.StreamChunk(
                stream_id="test-stream-1",
                payload=meta.encode("utf-8"),
                is_final=False,
            )
            # Data chunks
            for i in range(3):
                payload = json.dumps({"idx": i, "text": f"hello-{i}"})
                yield litserve_pb2.StreamChunk(
                    stream_id="test-stream-1",
                    payload=payload.encode("utf-8"),
                    is_final=False,
                )
            # Final chunk
            yield litserve_pb2.StreamChunk(
                stream_id="test-stream-1",
                payload=b"{}",
                is_final=True,
            )

        received = []
        for response in stub.BidirectionalStream(request_generator()):
            received.append(response)
            if response.is_final:
                break

        print(f"Received {len(received)} messages")
        # Should have at least 3 echo responses + 1 final
        assert len(received) >= 3, f"Expected at least 3 responses, got {len(received)}"

        # Verify echoes
        for i, msg in enumerate(received[:3]):
            data = json.loads(msg.payload.decode("utf-8"))
            assert "echo" in data, f"Message {i} missing echo: {data}"
            assert data["echo"]["idx"] == i, f"Message {i} wrong idx: {data}"

        channel.close()

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        try:
            os.unlink(temp_config)
        except OSError:
            pass
