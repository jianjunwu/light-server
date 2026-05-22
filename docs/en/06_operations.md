[简体中文](../zh/06_operations.md) | English

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

Open browser at `http://{host}:{http_port}/`.

### Features

- View loaded models and their status
- Real-time Prometheus metric charts
- Model load/unload operations
- Inference request test interface
- Analyzer report viewer

---

## Next Steps

- [Architecture](07_architecture.md)
- [FAQ](08_faq.md)
