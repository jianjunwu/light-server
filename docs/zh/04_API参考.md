[English](../en/04_API参考.md) | 简体中文

# API 参考

## HTTP REST 端点

### 推理端点

#### POST `/v2/models/{model_name}/infer`

执行模型推理。

**请求头：**

```
Content-Type: application/json
```

**请求体：**

任意 JSON，由模型的 `decode_request` 解析。

```json
{"input": "hello"}
```

**响应：**

```json
{"output": "hello"}
```

**状态码：**

| 状态码 | 含义 |
|--------|------|
| 200 | 推理成功 |
| 404 | 模型不存在或未加载 |
| 422 | 请求格式错误 |
| 500 | 推理过程中出错 |
| 503 | 服务忙，请求队列已满 |

#### POST `/v2/models/{model_name}/infer`（流式）

当模型配置 `stream: true` 时，响应为 `text/event-stream`。

### 管理端点

#### GET `/v2/models`

列出所有已加载模型。

**响应：**

```json
[
  {
    "name": "echo_model",
    "version": "1",
    "ready": true,
    "api_path": "/predict"
  }
]
```

#### GET `/v2/models/{model_name}/ready`

检查模型就绪状态。

**响应：**

```json
{"ready": true}
```

#### POST `/v2/repository/index`

列出仓库中所有可用模型（未加载的也会列出）。

**响应：**

```json
[
  {
    "name": "echo_model",
    "versions": ["1", "2"]
  }
]
```

#### POST `/v2/repository/models/{model_name}/load`

加载模型。

**请求体（可选）：**

```json
{"version": "2"}
```

不指定 `version` 时加载默认版本（`1`）。

**响应：**

```json
{"status": "loaded", "name": "echo_model", "version": "2"}
```

#### POST `/v2/repository/models/{model_name}/unload`

卸载模型。

**响应：**

```json
{"status": "unloaded", "name": "echo_model"}
```

### 指标端点

#### GET `/metrics`（`metrics_port`）

Prometheus 指标，包含：

- `litserve_*`：LitServe 内置指标
- 自定义指标：模型中定义的 Counter/Histogram
- 进程级 multiproc 指标

### WebUI 端点

#### GET `/`

Web UI 首页（当 `webui.enabled: true` 时）。

## gRPC 服务

gRPC 服务定义在 `src/light_server/grpc/proto/` 中。

### 方法列表

| 方法 | 请求 | 响应 | 说明 |
|------|------|------|------|
| `Predict` | `PredictRequest` | `PredictResponse` | 单条推理 |
| `StreamPredict` | `PredictRequest` | stream `PredictResponse` | 流式推理 |

### Proto 定义（简化）

```protobuf
service LitServe {
  rpc Predict(PredictRequest) returns (PredictResponse);
  rpc StreamPredict(PredictRequest) returns (stream PredictResponse);
}

message PredictRequest {
  string model_name = 1;
  string version = 2;
  bytes payload = 3;
}

message PredictResponse {
  bytes payload = 1;
}
```

**gRPC 端口：** 由 `server.grpc_port` 配置，默认 `8001`。

## 下一步

- [CLI 命令参考](05_CLI命令参考.md)
- [运维指南](06_运维指南.md)
