[简体中文](../zh/03_model_development.md) | English

# Model Development Guide

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
- `version`: Version string (e.g. `1`, `2`, `v1.0`), supports multiple versions side-by-side
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
