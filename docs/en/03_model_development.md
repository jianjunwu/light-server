[简体中文](../zh/03_模型开发指南.md) | English

# Model Development Guide

## Project Scaffolding (Recommended)

Use `light-server init` to quickly generate a project:

```bash
light-server init my_project --template llm --model-name my_llm
```

### Template Reference

| Template | Use Case | Contents |
|----------|----------|----------|
| `empty` | General purpose, start from scratch | Empty LitAPI skeleton |
| `llm` | Large language model serving | decode_request parses OpenAI-style requests |
| `cv-classify` | Image classification | Receives base64 image, outputs class label |
| `cv-detect` | Object detection | Receives base64 image, outputs bounding boxes |
| `nlp` | NLP text processing | Text classification / sentiment analysis skeleton |

The scaffold also generates `Dockerfile`, `docker-compose.yml`, `Makefile`, and GitHub Actions CI config, ready to use.

---

## Model Repository Convention

Follows the Triton-style layout:

```
model_repo/
  {model_name}/
    {version}/
      model.py       # Must contain a LitAPI subclass
      config.yaml    # Optional: max_batch_size, batch_timeout, etc.
```

- `model_name`: Directory name, used as identifier in admin APIs and inference endpoints
- `version`: Version string (e.g. `1`, `2`), supports multiple versions side-by-side
- `model.py`: Must contain a class that inherits from `LitAPI`

## LitAPI Lifecycle

```python
from light_server import LitAPI

class MyAPI(LitAPI):
    def setup(self, device):
        """Initialize model, load weights. device is assigned by light-server."""
        self.model = load_model()

    def decode_request(self, request, **kwargs):
        """Parse HTTP JSON request into input for predict."""
        return request["input"]

    def predict(self, x, **kwargs):
        """Run inference. When batching is enabled, x is a list."""
        return self.model(x)

    def encode_response(self, output, **kwargs):
        """Encode predict output into JSON response."""
        return {"result": output}
```

### Method Reference

| Method | When Called | Description |
|--------|-------------|-------------|
| `setup(device)` | Worker process startup | Called once per worker, `device` is the assigned accelerator |
| `decode_request(request, **kwargs)` | Per request | Parse HTTP request body into model input |
| `predict(x, **kwargs)` | Per request/batch | Execute actual inference |
| `encode_response(output, **kwargs)` | Per request | Encode into JSON returned to client |

### Reading Config in setup

```python
def setup(self, device):
    # Read custom fields from config.yaml
    self.max_length = self.config.get("max_length", 512)
    self.threshold = self.config.get("threshold", 0.5)
    self.logger.info(f"max_length={self.max_length}")
```

`self.config` is the parsed dict from `config.yaml`, `self.logger` is a structured logger.

## Batching

### Enable Batching

In `config.yaml`:

```yaml
max_batch_size: 8
batch_timeout: 0.01
```

### Batch Path in predict

```python
def predict(self, x, **kwargs):
    if isinstance(x, list):
        # Batch path: x = [input1, input2, ...]
        return [self.model(item) for item in x]
    # Single path
    return self.model(x)
```

### Tuning Suggestions

| Scenario | max_batch_size | batch_timeout |
|----------|---------------|---------------|
| High concurrency, latency-sensitive | 4-8 | 0.001-0.01s |
| Throughput-first | 16-32 | 0.05-0.1s |
| Limited GPU memory | 2-4 | 0.01s |

## Streaming Response

### Enable Streaming

```yaml
stream: true
```

### predict Returns Generator

```python
def predict(self, x, **kwargs):
    for token in self.model.generate(x):
        yield token
```

`encode_response` receives `yield` values chunk by chunk and streams them to the client.

## Custom Prometheus Metrics

```python
from prometheus_client import Counter, Histogram

class MyAPI(LitAPI):
    request_counter = Counter("my_requests_total", "Total requests")
    latency = Histogram("my_latency_seconds", "Latency", buckets=[0.001, 0.01, 0.1, 1.0])

    def predict(self, x, **kwargs):
        self.request_counter.inc()
        with self.latency.time():
            return self.model(x)
```

Custom metrics are automatically aggregated via multiproc mode, viewable at `:metrics_port/metrics`.

## Version Control

### Multiple Versions

```
model_repo/
  my_model/
    1/
      model.py
      config.yaml
    2/
      model.py
      config.yaml
```

### Switching Versions

```bash
# Load a specific version
curl -X POST http://127.0.0.1:8000/v2/repository/models/my_model/load \
  -H "Content-Type: application/json" \
  -d '{"version": "2"}'

# Check active version
curl http://127.0.0.1:8000/v2/models/my_model
```

### Hot Reload

Enable in `config.yaml`:

```yaml
hot_reload: true
hot_reload_interval: 1.0
hot_reload_patterns:
  - "*.py"
  - "*.yaml"
```

After modifying `model.py` or `config.yaml`, the model is automatically reloaded without restarting the server.

#### Custom Reload Hook

You can optionally implement `on_file_changed(changed_files)` in your LitAPI subclass to handle reload events customly:

```python
def on_file_changed(self, changed_files):
    """Called when hot reload detects file changes."""
    for path in changed_files:
        print(f"File changed: {path}")
    # Return True to proceed with standard reload, False to skip
    return True
```

## Model Lifecycle Hooks

A LitAPI subclass can **optionally** implement three hooks that run before/after inference and during readiness checks.

### on_request — Before Enqueue

```python
def on_request(self, payload, request_meta):
    """Called in the main process before the request is queued."""
    headers = request_meta.get("headers", {})
    auth = headers.get("authorization", "anonymous")
    payload["_auth"] = auth
    return payload
```

**`request_meta` contains:**

| Field | Description |
|-------|-------------|
| `headers` | Request headers dict |
| `query_params` | URL query parameters |
| `client_host` | Client IP address |
| `method` | HTTP method (GET/POST/...) |
| `url` | Full request URL |
| `path_params` | `{"model_name": ..., "version": ...}` |

### on_response — Before Returning to Client

```python
def on_response(self, response, response_meta):
    """Called in the main process after the worker responds, before sending to client."""
    response["_meta"] = {
        "model_name": response_meta.get("model_name"),
        "version": response_meta.get("version"),
        "status": response_meta.get("status"),
    }
    return response
```

**`response_meta` contains:**

| Field | Description |
|-------|-------------|
| `model_name` | Model name |
| `version` | Version string |
| `request_meta` | Original metadata injected by `on_request` |
| `status` | `"ok"` or `"error"` |

### health_check — Model-Level Health Probe

```python
def health_check(self):
    """Called by GET /v2/models/{name}/ready."""
    return {"status": "healthy", "gpu": 0.5}
```

The returned dict is attached to the `/ready` response under `model_status`. If an exception is raised, it is gracefully caught and returned as `{"status": "error", "error": "..."}`.

> All hooks are optional. Behavior is identical to standard LitAPI when not implemented.

See [`examples/11_hooks_and_endpoints`](../../examples/11_hooks_and_endpoints/) for a complete example.

---

## Dynamic Endpoints (Custom Routes)

Place `*_endpoint.py` files in the `model_repo` root to auto-register them as FastAPI routes.

### Naming Convention

The file stem (without `_endpoint.py`) becomes the route path:

| Filename | Route |
|----------|-------|
| `health_endpoint.py` | `GET /health` (overrides default) |
| `status_endpoint.py` | `GET /status` |
| `webhook_endpoint.py` | `GET /webhook` |

### Basic Handler

```python
# model_repo/health_endpoint.py
def handler(request, server):
    return {"status": "ok", "custom": True}
```

### Custom HTTP Methods

```python
# model_repo/webhook_endpoint.py
methods = ["POST"]

def handler(request, server):
    return {"received": True}
```

### Async Handler

```python
# model_repo/status_endpoint.py
async def handler(request, server):
    loaded = server.registry.list_loaded()
    return {"models": loaded}
```

### Handler Arguments

- `request` — FastAPI `Request` object; you can call `await request.json()`, `request.headers`, etc.
- `server` — `LightServer` instance; access `registry`, `model_manager`, `config`, etc.

See [`examples/11_hooks_and_endpoints`](../../examples/11_hooks_and_endpoints/) for a complete example.

---

## Auxiliary Modules

`.py` files in the same directory as `model.py` can be imported:

```python
# model_repo/my_model/1/utils.py
def preprocess(x):
    return x.lower()

# model_repo/my_model/1/model.py
import utils

def decode_request(self, request, **kwargs):
    return utils.preprocess(request["text"])
```

## Next Steps

- [API Reference](04_api_reference.md)
- [Advanced Example: Batching + Metrics + Hot Reload](../../examples/02_advanced/)
