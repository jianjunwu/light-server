import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _start_server_with_grpc(repo_path: Path):
    """Start light-server with gRPC enabled and return (proc, temp_config_path, base_url, grpc_target)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(f"""
grpc:
  enabled: true
  max_workers: 10
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
""")
        temp_config = f.name

    proc = subprocess.Popen(
        [sys.executable, "-m", "light_server", "serve", "--config", temp_config],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    base = "http://127.0.0.1:18000"
    grpc_target = "127.0.0.1:18001"

    import requests
    for _ in range(60):
        time.sleep(0.2)
        try:
            resp = requests.get(f"{base}/health", timeout=2)
            if resp.status_code == 200:
                break
        except requests.ConnectionError:
            continue
    else:
        proc.terminate()
        proc.wait(timeout=5)
        raise RuntimeError("Server did not start")

    time.sleep(0.5)
    return proc, temp_config, base, grpc_target


def _cleanup(proc, temp_config):
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


def test_grpc_predict(isolated_model_repo):
    """E2E test: gRPC unary Predict for test_model."""
    proc, temp_config, base, grpc_target = _start_server_with_grpc(isolated_model_repo)
    try:
        import grpc
        from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

        # Wait for test_model to be ready (loaded by config)
        import requests
        for _ in range(20):
            time.sleep(0.3)
            resp = requests.get(f"{base}/v2/models/test_model/ready", timeout=5)
            if resp.json().get("ready"):
                break
        else:
            raise RuntimeError("Model did not become ready")

        channel = grpc.insecure_channel(grpc_target)
        stub = litserve_pb2_grpc.InferenceStub(channel)

        request = litserve_pb2.PredictRequest(
            model_name="test_model",
            payload=json.dumps({"input": 4.0}).encode("utf-8"),
        )
        response = stub.Predict(request)
        data = json.loads(response.payload.decode("utf-8"))
        print(f"Predict response: {data}")
        assert "output" in data
        channel.close()

    finally:
        _cleanup(proc, temp_config)


def test_grpc_stream_predict(isolated_model_repo):
    """E2E test: gRPC unary-stream StreamPredict for stream_model."""
    proc, temp_config, base, grpc_target = _start_server_with_grpc(isolated_model_repo)
    try:
        import grpc
        import requests
        from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

        # Load stream model
        resp = requests.post(
            f"{base}/v2/repository/models/stream_model/load", timeout=10
        )
        assert resp.status_code == 200

        for _ in range(20):
            time.sleep(0.3)
            resp = requests.get(f"{base}/v2/models/stream_model/ready", timeout=5)
            if resp.json().get("ready"):
                break
        else:
            raise RuntimeError("Model did not become ready")

        channel = grpc.insecure_channel(grpc_target)
        stub = litserve_pb2_grpc.InferenceStub(channel)

        request = litserve_pb2.PredictRequest(
            model_name="stream_model",
            payload=json.dumps({"text": "hello"}).encode("utf-8"),
        )
        received = []
        for response in stub.StreamPredict(request):
            received.append(response)
            data = json.loads(response.payload.decode("utf-8"))
            if "echo" in data:
                break
            if len(received) > 10:
                break

        print(f"StreamPredict received {len(received)} chunks")
        assert len(received) >= 1
        channel.close()

    finally:
        _cleanup(proc, temp_config)


def test_grpc_model_control(isolated_model_repo):
    """E2E test: gRPC ModelControl (ready, load, unload)."""
    proc, temp_config, base, grpc_target = _start_server_with_grpc(isolated_model_repo)
    try:
        import grpc
        import requests
        from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

        channel = grpc.insecure_channel(grpc_target)
        stub = litserve_pb2_grpc.ModelControlStub(channel)

        # ModelReady for non-loaded model
        resp = stub.ModelReady(litserve_pb2.ModelReadyRequest(model_name="stream_model"))
        assert resp.ready is False

        # Load via HTTP admin, then check via gRPC
        http_resp = requests.post(
            f"{base}/v2/repository/models/stream_model/load", timeout=10
        )
        assert http_resp.status_code == 200

        for _ in range(20):
            time.sleep(0.3)
            resp = stub.ModelReady(litserve_pb2.ModelReadyRequest(model_name="stream_model"))
            if resp.ready:
                break
        else:
            raise RuntimeError("Model did not become ready")

        # RepositoryIndex
        resp = stub.RepositoryIndex(litserve_pb2.Empty())
        assert any(m.name == "stream_model" for m in resp.models)

        # Unload
        resp = stub.UnloadModel(litserve_pb2.UnloadModelRequest(model_name="stream_model"))
        assert resp.success is True

        time.sleep(0.5)
        resp = stub.ModelReady(litserve_pb2.ModelReadyRequest(model_name="stream_model"))
        assert resp.ready is False

        channel.close()

    finally:
        _cleanup(proc, temp_config)


def test_grpc_bidirectional_stream(isolated_model_repo):
    """E2E test: start server with gRPC enabled, connect via BidirectionalStream."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(f"""
grpc:
  enabled: true
  max_workers: 10
load_models:
- test_model
metrics:
  enabled: false
model_repository:
  control_mode: explicit
  path: {isolated_model_repo}
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
        cwd=str(PROJECT_ROOT),
    )

    try:
        base = "http://127.0.0.1:18000"
        grpc_target = "127.0.0.1:18001"

        import requests
        for _ in range(60):
            time.sleep(0.2)
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


def test_grpc_predict_model_not_ready(isolated_model_repo):
    """E2E test: gRPC Predict for unloaded model should return NOT_FOUND."""
    proc, temp_config, base, grpc_target = _start_server_with_grpc(isolated_model_repo)
    try:
        import grpc
        from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

        channel = grpc.insecure_channel(grpc_target)
        stub = litserve_pb2_grpc.InferenceStub(channel)

        request = litserve_pb2.PredictRequest(
            model_name="nonexistent_model",
            payload=json.dumps({"input": 1.0}).encode("utf-8"),
        )
        try:
            stub.Predict(request)
            assert False, "Expected NOT_FOUND error"
        except grpc.RpcError as e:
            assert e.code() == grpc.StatusCode.NOT_FOUND
            assert "not ready" in e.details().lower() or "nonexistent_model" in e.details()

        channel.close()
    finally:
        _cleanup(proc, temp_config)


def test_grpc_stream_predict_model_not_ready(isolated_model_repo):
    """E2E test: gRPC StreamPredict for unloaded model should return NOT_FOUND."""
    proc, temp_config, base, grpc_target = _start_server_with_grpc(isolated_model_repo)
    try:
        import grpc
        from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

        channel = grpc.insecure_channel(grpc_target)
        stub = litserve_pb2_grpc.InferenceStub(channel)

        request = litserve_pb2.PredictRequest(
            model_name="nonexistent_model",
            payload=json.dumps({"text": "hello"}).encode("utf-8"),
        )
        try:
            list(stub.StreamPredict(request))
            assert False, "Expected NOT_FOUND error"
        except grpc.RpcError as e:
            assert e.code() == grpc.StatusCode.NOT_FOUND

        channel.close()
    finally:
        _cleanup(proc, temp_config)


def test_grpc_bidirectional_stream_missing_model_name(isolated_model_repo):
    """E2E test: BidirectionalStream first chunk without model_name should fail."""
    proc, temp_config, base, grpc_target = _start_server_with_grpc(isolated_model_repo)
    try:
        import grpc
        from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

        channel = grpc.insecure_channel(grpc_target)
        stub = litserve_pb2_grpc.InferenceStub(channel)

        def request_generator():
            # First chunk without model_name
            yield litserve_pb2.StreamChunk(
                stream_id="test-bad",
                payload=json.dumps({"version": "1"}).encode("utf-8"),
                is_final=False,
            )

        try:
            list(stub.BidirectionalStream(request_generator()))
            assert False, "Expected INVALID_ARGUMENT error"
        except grpc.RpcError as e:
            assert e.code() == grpc.StatusCode.INVALID_ARGUMENT
            assert "model_name" in e.details().lower()

        channel.close()
    finally:
        _cleanup(proc, temp_config)


def test_grpc_bidirectional_stream_model_not_ready(isolated_model_repo):
    """E2E test: BidirectionalStream for unloaded model should return NOT_FOUND."""
    proc, temp_config, base, grpc_target = _start_server_with_grpc(isolated_model_repo)
    try:
        import grpc
        from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

        channel = grpc.insecure_channel(grpc_target)
        stub = litserve_pb2_grpc.InferenceStub(channel)

        def request_generator():
            yield litserve_pb2.StreamChunk(
                stream_id="test-not-ready",
                payload=json.dumps({"model_name": "nonexistent_model"}).encode("utf-8"),
                is_final=False,
            )

        try:
            list(stub.BidirectionalStream(request_generator()))
            assert False, "Expected NOT_FOUND error"
        except grpc.RpcError as e:
            assert e.code() == grpc.StatusCode.NOT_FOUND

        channel.close()
    finally:
        _cleanup(proc, temp_config)


def test_grpc_predict_invalid_json(isolated_model_repo):
    """E2E test: gRPC Predict with invalid JSON payload should return INVALID_ARGUMENT."""
    proc, temp_config, base, grpc_target = _start_server_with_grpc(isolated_model_repo)
    try:
        import requests
        import grpc
        from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

        # Wait for test_model to be ready
        for _ in range(20):
            time.sleep(0.3)
            resp = requests.get(f"{base}/v2/models/test_model/ready", timeout=5)
            if resp.json().get("ready"):
                break
        else:
            raise RuntimeError("Model did not become ready")

        channel = grpc.insecure_channel(grpc_target)
        stub = litserve_pb2_grpc.InferenceStub(channel)

        request = litserve_pb2.PredictRequest(
            model_name="test_model",
            payload=b"not-valid-json",
        )
        try:
            stub.Predict(request)
            assert False, "Expected INVALID_ARGUMENT error"
        except grpc.RpcError as e:
            assert e.code() == grpc.StatusCode.INVALID_ARGUMENT

        channel.close()
    finally:
        _cleanup(proc, temp_config)
