[简体中文](../zh/04_API参考.md) | English

# API Reference

## HTTP REST Endpoints

### Service Health & Info

#### GET `/health`

Health check endpoint.

**Response:**

```
ok
```

**Status Codes:**

| Code | Meaning |
|------|---------|
| 200 | Service is healthy |

#### GET `/info`

Get basic server information.

**Response:**

```json
{
  "server": "light-server",
  "version": "0.1.0",
  "loaded_models": [...]
}
```

### Inference Endpoints

#### POST `/v2/models/{model_name}/infer`

Run inference against the **currently active version** of a model.

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
{"result": "hello"}
```

**Status Codes:**

| Code | Meaning |
|------|---------|
| 200 | Inference successful |
| 400 | Invalid model name or version format |
| 404 | Model not found or not loaded |
| 429 | Service busy, request queue is full |
| 500 | Error during inference |
| 504 | Inference timeout |

#### POST `/v2/models/{model_name}/versions/{version}/infer`

Run inference against a **specific version** of a model.

Parameters and response are the same as above. The `version` in the path is the specific version number (e.g. `1`, `2`).

#### WebSocket `/v2/models/{model_name}/stream`

Open a bidirectional WebSocket streaming inference connection to the **currently active version** of a model.

The client sends JSON messages, and the server returns inference results chunk by chunk.

**Message format (client -> server):**

```json
{"input": "hello"}
```

**Message format (server -> client):**

```json
{"token": "he"}
```

The server automatically closes the connection when the stream ends.

#### WebSocket `/v2/models/{model_name}/versions/{version}/stream`

Open a WebSocket streaming inference connection to a **specific version** of a model.

### Admin Endpoints

#### GET `/v2/models`

List all loaded models.

**Response:**

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

Check model readiness.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `version` | str | No | Specific version to check; defaults to active version |

**Response:**

```json
{
  "name": "echo_model",
  "version": "1",
  "ready": true,
  "active_version": "1"
}
```

#### GET `/v2/models/{model_name}/versions`

List all **loaded** versions for a model.

**Response:**

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

List all available models in the repository (including unloaded ones).

**Response:**

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

Load a specific version of a model from the repository.

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `version` | str | No | `1` | Version to load |

**Response:**

```json
{
  "success": true,
  "message": "Model echo_model version 2 loaded"
}
```

**Status Codes:**

| Code | Meaning |
|------|---------|
| 200 | Load successful |
| 400 | Invalid model name or version format, or load failed |

#### POST `/v2/repository/models/{model_name}/unload`

Unload a model. If a version is specified, only that version is unloaded.

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `version` | str | No | `null` | Version to unload; omit to unload all versions |

**Response:**

```json
{
  "success": true,
  "message": "Model echo_model version 1 unloaded"
}
```

#### POST `/v2/models/{model_name}/versions/{version}/activate`

Set the specified version as the **active version** (subsequent inference requests without a version will be routed to this version).

**Response:**

```json
{
  "success": true,
  "message": "Model echo_model version 2 is now active",
  "active_version": "2"
}
```

**Status Codes:**

| Code | Meaning |
|------|---------|
| 200 | Activation successful |
| 400 | Invalid model name or version format, or version is not ready |

### Metrics Endpoint

#### GET `/metrics` (`metrics_port`)

Prometheus metrics, including:

- `litserve_*`: Built-in LitServe metrics
- Custom metrics: Counter/Histogram defined in models
- Process-level multiproc metrics

### WebUI Endpoints

#### GET `/ui/`

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
