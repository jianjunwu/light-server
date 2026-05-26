[简体中文](../zh/06_运维指南.md) | English

# Operations Guide

## Prometheus Metrics

### Enable Metrics

```yaml
metrics:
  enabled: true
```

Metrics endpoint: `http://{host}:{metrics_port}/metrics`, default `http://127.0.0.1:8002/metrics`.

### Built-in Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `litserve_request_duration_seconds` | Histogram | Request processing latency |
| `litserve_requests_total` | Counter | Total requests |
| `litserve_active_requests` | Gauge | Active requests |

### Custom Metrics

Define in your model:

```python
from prometheus_client import Counter, Histogram

class MyAPI(LitAPI):
    input_tokens = Counter("my_input_tokens_total", "Input tokens")
    predict_latency = Histogram("my_predict_seconds", "Predict latency")

    def predict(self, x, **kwargs):
        self.input_tokens.inc(len(x))
        with self.predict_latency.time():
            return self.model(x)
```

Custom metrics are automatically aggregated via multiproc mode.

---

## Logging

### Log Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| `queue` | Asynchronous queue writing | High concurrency, default |
| `file` | Direct file writing | Simple scenarios |

### Log Configuration

```yaml
logging:
  mode: "queue"
  level: "info"
  format: "json"
  info_output: "./logs/info.log"
  error_output: "./logs/error.log"
  rotate_by: "size"
  max_size: 100
  backup_count: 7
```

### Formats

**JSON format (default):**

```json
{"timestamp":"2024-01-01T12:00:00","level":"INFO","message":"Model loaded","model":"test_model"}
```

**Text format:**

```
2024-01-01 12:00:00 [INFO] Model loaded: test_model
```

### Using Logger in Models

```python
def predict(self, x, **kwargs):
    self.logger.info(f"predict called with input={x}")
    self.logger.warning("Something unexpected")
    return self.model(x)
```

---

## Artifact Packaging

### Pack Model

```bash
light-server pack model_repo/test_model --version 1.0.0
```

Output: `artifacts/test_model-1.0.0-{build_id}.lma`

`.lma` is a ZIP archive containing:

- `manifest.json`: Metadata (name, version, build ID, file list, hashes)
- Model files

> **Runtime loading:** The server automatically scans `.lma` files in the model repository at startup (via `_scan_artifact_models`). You can place `.lma` artifacts directly in `model_repo/` without unpacking — the server extracts them to a cache and loads them like regular models.

### Signing (Optional)

```bash
light-server pack model_repo/test_model --version 1.0.0 --sign-key private.pem --signer "ci@company.com"
```

### Unpack

```bash
light-server unpack artifact.lma --to ./model_repo
```

### Verification

```bash
light-server unpack artifact.lma --verify-key public.pem --dry-run
```

---

## Model Analyzer

Analyzer automatically searches for optimal configuration combinations:

```bash
light-server analyze --model test_model --output-dir ./reports
```

Search space:

- `max_batch_size`: 1, 2, 4, 8, 16
- `batch_timeout`: 0.001, 0.01, 0.1
- `concurrency`: 1, 2, 4, 8, 16

Report output:

```json
{
  "model": "test_model",
  "pareto_frontier": [
    {
      "max_batch_size": 4,
      "batch_timeout": 0.01,
      "concurrency": 8,
      "throughput": 520.5,
      "latency_p99": 25.3
    }
  ]
}
```

Pareto frontier configurations achieve the best balance between throughput and latency.

---

## Web UI

### Enable

```yaml
webui:
  enabled: true
```

### Access

Open browser at `http://{host}:{http_port}/`, default `http://127.0.0.1:8000/`.

### Features and Operations

**Model Management**
- Home page shows all loaded models with name, version, and readiness status
- Click a model card to view details (API path, batching config, accelerator)
- Use "Load" / "Unload" buttons to dynamically manage models without restarting

**Inference Testing**
- Select a model and enter a JSON payload in the test panel
- Click "Send Request" to see the response result and request latency in real time
- Copy the generated curl command for terminal reproduction

**Metrics Monitoring**
- Automatically pulls Prometheus data from `:metrics_port/metrics`
- Visualizes request latency distribution, throughput trends, and active request counts
- Filter by model dimension to quickly locate performance bottlenecks

**Analyzer Reports**
- If `light-server analyze` has been run, reports are automatically displayed in WebUI
- View the Pareto frontier configuration list and apply recommended parameters with one click

### Security

In production, place WebUI and admin APIs behind a reverse proxy (e.g., Nginx) with authentication:

```nginx
location / {
    auth_basic "Light Server Admin";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://127.0.0.1:8000;
}

---

## Next Steps

- [Architecture](07_architecture.md)
- [FAQ](08_faq.md)
