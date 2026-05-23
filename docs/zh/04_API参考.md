[English](../en/04_api_reference.md) | 简体中文

# API 参考

## HTTP REST 端点

### 服务健康与信息

#### GET `/health`

健康检查端点。

**响应：**

```
ok
```

**状态码：**

| 状态码 | 含义 |
|--------|------|
| 200 | 服务正常运行 |

#### GET `/info`

获取服务基本信息。

**响应：**

```json
{
  "server": "light-server",
  "version": "0.1.0",
  "loaded_models": [...]
}
```

### 推理端点

#### POST `/v2/models/{model_name}/infer`

对模型的**当前激活版本**执行推理。

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
{"result": "hello"}
```

**状态码：**

| 状态码 | 含义 |
|--------|------|
| 200 | 推理成功 |
| 400 | 模型名或版本号格式无效 |
| 404 | 模型不存在或未加载 |
| 429 | 服务忙，请求队列已满 |
| 500 | 推理过程中出错 |
| 504 | 推理超时 |

#### POST `/v2/models/{model_name}/versions/{version}/infer`

对模型的**指定版本**执行推理。

参数与响应同上，路径中的 `version` 为具体版本号（如 `1`、`2`）。

#### WebSocket `/v2/models/{model_name}/stream`

对模型的**当前激活版本**建立双向 WebSocket 流式推理连接。

客户端通过 WebSocket 发送 JSON 消息，服务端逐 chunk 返回推理结果。

**消息格式（客户端 -> 服务端）：**

```json
{"input": "hello"}
```

**消息格式（服务端 -> 客户端）：**

```json
{"token": "he"}
```

流结束时服务端自动关闭连接。

#### WebSocket `/v2/models/{model_name}/versions/{version}/stream`

对模型的**指定版本**建立 WebSocket 流式推理连接。

### 管理端点

#### GET `/v2/models`

列出所有已加载模型。

**响应：**

```json
{
  "models": [
    {
      "name": "echo_model",
      "version": "1",
      "status": "READY",
      "model_type": "litapi",
      "config": {...}
    }
  ]
}
```

#### GET `/v2/models/{model_name}/ready`

检查模型就绪状态。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `version` | str | 否 | 指定版本号，不指定则检查激活版本 |

**响应：**

```json
{
  "name": "echo_model",
  "version": "1",
  "ready": true,
  "active_version": "1"
}
```

#### GET `/v2/models/{model_name}/versions`

列出模型所有**已加载**的版本。

**响应：**

```json
{
  "name": "echo_model",
  "active_version": "1",
  "versions": [
    {
      "name": "echo_model",
      "version": "1",
      "status": "READY",
      "model_type": "litapi"
    }
  ]
}
```

#### POST `/v2/repository/index`

列出仓库中所有可用模型（包括未加载的）。

**响应：**

```json
{
  "models": [
    {
      "name": "echo_model",
      "versions": ["1", "2"]
    }
  ]
}
```

#### POST `/v2/repository/models/{model_name}/load`

从仓库加载模型的指定版本。

**查询参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `version` | str | 否 | `1` | 要加载的版本号 |

**响应：**

```json
{
  "success": true,
  "message": "Model echo_model version 2 loaded"
}
```

**状态码：**

| 状态码 | 含义 |
|--------|------|
| 200 | 加载成功 |
| 400 | 模型名或版本号格式无效，或加载失败 |

#### POST `/v2/repository/models/{model_name}/unload`

卸载模型。若指定版本，则仅卸载该版本。

**查询参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `version` | str | 否 | `null` | 要卸载的版本号，不指定则卸载所有版本 |

**响应：**

```json
{
  "success": true,
  "message": "Model echo_model version 1 unloaded"
}
```

#### POST `/v2/models/{model_name}/versions/{version}/activate`

将指定版本设为**激活版本**（后续无版本号的推理请求将路由到该版本）。

**响应：**

```json
{
  "success": true,
  "message": "Model echo_model version 2 is now active",
  "active_version": "2"
}
```

**状态码：**

| 状态码 | 含义 |
|--------|------|
| 200 | 激活成功 |
| 400 | 模型名或版本号格式无效，或该版本未就绪 |

### 指标端点

#### GET `/metrics`（`metrics_port`）

Prometheus 指标，包含：

- `litserve_*`：LitServe 内置指标
- 自定义指标：模型中定义的 Counter/Histogram
- 进程级 multiproc 指标

### WebUI 端点

#### GET `/ui/`

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
