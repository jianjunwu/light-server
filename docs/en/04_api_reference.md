[简体中文](../zh/04_api_reference.md) | English

# API Reference

## HTTP REST Endpoints

### Inference Endpoint

#### POST `/v2/models/{model_name}/infer`

Execute model inference.

**Headers:**

```
Content-Type: application/json
```

**Request Body:**

Any JSON, parsed by the model's `decode_request`.

```json
{"input": "hello"}
```

**Response:**

```json
{"output": "hello"}
```

**Status Codes:**

| Code | Meaning |
|------|---------|
| 200 | Inference successful |
| 404 | Model not found or not loaded |
| 422 | Invalid request format |
| 500 | Error during inference |
| 503 | Service busy, request queue full |

#### POST `/v2/models/{model_name}/infer` (Streaming)

When model config has `stream: true`, response is `text/event-stream`.

### Admin Endpoints

#### GET `/v2/models`

List all loaded models.

**Response:**

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

Check model readiness.

**Response:**

```json
{"ready": true}
```

#### POST `/v2/repository/index`

List all available models in the repository (including unloaded ones).

**Response:**

```json
[
  {
    "name": "echo_model",
    "versions": ["1", "2"]
  }
]
```

#### POST `/v2/repository/models/{model_name}/load`

Load a model.

**Request Body (optional):**

```json
{"version": "2"}
```

When `version` is omitted, the default version (`1`) is loaded.

**Response:**

```json
{"status": "loaded", "name": "echo_model", "version": "2"}
```

#### POST `/v2/repository/models/{model_name}/unload`

Unload a model.

**Response:**

```json
{"status": "unloaded", "name": "echo_model"}
```

### Metrics Endpoint

#### GET `/metrics` (`metrics_port`)

Prometheus metrics, including:

- `litserve_*`: Built-in LitServe metrics
- Custom metrics: Counter/Histogram defined in models
- Process-level multiproc metrics

### WebUI Endpoint

#### GET `/`

Web UI home page (when `webui.enabled: true`).

## gRPC Service

gRPC service definitions are in `src/light_server/grpc/proto/`.

### Method List

| Method | Request | Response | Description |
|--------|---------|----------|-------------|
| `Predict` | `PredictRequest` | `PredictResponse` | Single inference |
| `StreamPredict` | `PredictRequest` | stream `PredictResponse` | Streaming inference |

### Proto Definition (Simplified)

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

**gRPC Port:** Configured by `server.grpc_port`, default `8001`.

## Next Steps

- [CLI Reference](05_cli_reference.md)
- [Operations Guide](06_operations.md)
