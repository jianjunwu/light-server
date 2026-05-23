"""Compare HTTP REST vs gRPC latency for the same inference task."""

import json
import time

import requests


def http_infer(text: str) -> dict:
    resp = requests.post(
        "http://127.0.0.1:8000/v2/models/hello_model/infer",
        headers={"Content-Type": "application/json"},
        json={"text": text},
    )
    resp.raise_for_status()
    return resp.json()


def grpc_infer(text: str) -> dict:
    import grpc
    from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

    channel = grpc.insecure_channel("127.0.0.1:8001")
    stub = litserve_pb2_grpc.InferenceStub(channel)

    request = litserve_pb2.PredictRequest(
        model_name="hello_model",
        payload=json.dumps({"text": text}).encode("utf-8"),
    )
    response = stub.Predict(request)
    channel.close()
    return json.loads(response.payload.decode("utf-8"))


def benchmark_http(count: int = 100) -> float:
    start = time.perf_counter()
    for i in range(count):
        http_infer(f"hello {i}")
    return time.perf_counter() - start


def benchmark_grpc(count: int = 100) -> float:
    import grpc
    from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

    channel = grpc.insecure_channel("127.0.0.1:8001")
    stub = litserve_pb2_grpc.InferenceStub(channel)

    start = time.perf_counter()
    for i in range(count):
        request = litserve_pb2.PredictRequest(
            model_name="hello_model",
            payload=json.dumps({"text": f"hello {i}"}).encode("utf-8"),
        )
        response = stub.Predict(request)
        json.loads(response.payload.decode("utf-8"))

    channel.close()
    return time.perf_counter() - start


def main():
    print("🔗 HTTP REST vs gRPC Latency Comparison\n")

    # Warm-up
    print("Warming up...")
    http_infer("warmup")
    grpc_infer("warmup")
    print("Done.\n")

    count = 100

    print(f"📡 HTTP REST  — {count} requests...")
    http_time = benchmark_http(count)
    print(f"   Total: {http_time:.3f}s  |  Avg: {http_time/count*1000:.2f}ms")

    print(f"\n⚡ gRPC       — {count} requests...")
    grpc_time = benchmark_grpc(count)
    print(f"   Total: {grpc_time:.3f}s  |  Avg: {grpc_time/count*1000:.2f}ms")

    speedup = http_time / grpc_time
    print(f"\n📈 gRPC is {speedup:.2f}× faster than HTTP REST")

    # Single request sample
    print("\n📝 Sample response:")
    result = grpc_infer("I love light-server")
    print(f"   Input:  {result['original']}")
    print(f"   Output: {result['enhanced']}")
    print(f"   Mood:   {result['mood']}")


if __name__ == "__main__":
    main()
