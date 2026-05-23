# 08_grpc_client — gRPC 高性能调用

演示 light-server 的 gRPC 推理端点，并与 HTTP REST 进行延迟对比。gRPC 使用 Protocol Buffers + HTTP/2，通常比 REST JSON 更快、更省带宽。

## 🎯 30 秒体验

```bash
cd examples/08_grpc_client
./run.sh
```

终端会自动完成：验证模型 → 启动 gRPC 服务 → 并发发送 100 条 HTTP 和 gRPC 请求 → 输出延迟对比。

## 📸 运行效果

```
🔗 HTTP REST vs gRPC Latency Comparison

Warming up...
Done.

📡 HTTP REST  — 100 requests...
   Total: 0.523s  |  Avg: 5.23ms

⚡ gRPC       — 100 requests...
   Total: 0.312s  |  Avg: 3.12ms

📈 gRPC is 1.68× faster than HTTP REST

📝 Sample response:
   Input:  I love light-server
   Output: I love light-server ❤️ That's fantastic!
   Mood:   positive
```

## 核心原理

### gRPC 服务端配置 (`server.yaml`)

```yaml
grpc:
  enabled: true
  max_workers: 10
```

### gRPC 客户端 (`client.py`)

```python
import grpc
from light_server.grpc.proto import litserve_pb2, litserve_pb2_grpc

channel = grpc.insecure_channel("127.0.0.1:8001")
stub = litserve_pb2_grpc.InferenceStub(channel)

request = litserve_pb2.PredictRequest(
    model_name="hello_model",
    payload=json.dumps({"text": "hello"}).encode("utf-8"),
)
response = stub.Predict(request)
result = json.loads(response.payload.decode("utf-8"))
```

### 可用 gRPC 服务

| 服务 | 方法 | 说明 |
|------|------|------|
| `Inference` | `Predict` | 单次推理（unary-unary） |
| `Inference` | `StreamPredict` | 流式推理（unary-stream） |
| `Inference` | `BidirectionalStream` | 双向流式（stream-stream） |
| `ModelControl` | `ModelReady` | 查询模型就绪状态 |
| `ModelControl` | `RepositoryIndex` | 列出仓库中的模型 |
| `ModelControl` | `LoadModel` | 加载模型 |
| `ModelControl` | `UnloadModel` | 卸载模型 |

## 手动运行

### 1. 启动服务

```bash
cd examples/08_grpc_client
light-server serve --config server.yaml
```

### 2. 运行对比客户端

```bash
pip install grpcio
python client.py
```

## 模型说明

- **`model.py`**：与 `01_quickstart` 相同的智能文本增强模型
- **`server.yaml`**：同时开启 HTTP (8000) 和 gRPC (8001)
- **`client.py`**：分别用 HTTP REST 和 gRPC 发送 100 条请求，对比总耗时和平均延迟

## 下一步

👉 前往 [`09_openai_compatible`](../09_openai_compatible/)，体验 OpenAI SDK 直接调用 light-server。
