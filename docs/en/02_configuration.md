[简体中文](../zh/02_配置详解.md) | English

# Configuration Guide

`light-server` uses YAML configuration files. Configuration is split into server-level (`server.yaml`) and model-level (`config.yaml`).

## Server Configuration (server.yaml)

### Full Template

```yaml
server:
  host: "0.0.0.0"
  http_port: 8000
  grpc_port: 8001
  metrics_port: 8002
  accelerator: "auto"
  devices: "auto"
  workers_per_device: 1
  timeout: 30.0
  log_level: "info"
  num_api_servers: 1

grpc:
  enabled: true
  max_workers: 10

metrics:
  enabled: true

logging:
  mode: "queue"
  level: "info"
  format: "json"
  output: null
  info_output: null
  error_output: null
  rotation: "daily"
  rotate_by: "none"
  max_size: 100
  when: "midnight"
  backup_count: 7

model_repository:
  path: "./model_repo"
  control_mode: "explicit"
  poll_interval: 5

load_models:
  - model_a
  - model_b

models:
  - name: model_a
    version: "1"
    api_path: "/predict"
    max_batch_size: 4
    batch_timeout: 0.01
    stream: false
    accelerator: null
    devices: null
    workers_per_device: null

webui:
  enabled: true
  report_retention_days: 30
```

### Field Reference

#### `server`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | str | `0.0.0.0` | Bind address, use `127.0.0.1` for local only |
| `http_port` | int | `8000` | HTTP inference port |
| `grpc_port` | int | `8001` | gRPC port |
| `metrics_port` | int | `8002` | Prometheus metrics port |
| `accelerator` | str | `auto` | Accelerator type: `auto`/`cpu`/`gpu` |
| `devices` | int/str | `auto` | Number of devices, `auto` for auto-detect |
| `workers_per_device` | int | `1` | Worker processes per device |
| `timeout` | float | `30.0` | Request timeout in seconds |
| `log_level` | str | `info` | Log level: `debug`/`info`/`warning`/`error` |
| `num_api_servers` | int | `1` | HTTP API server processes, keep 1 for shared state |

#### `model_repository`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | str | `./model_repo` | Model repository root directory, supports `${VAR}` env vars |
| `control_mode` | str | `explicit` | Control mode, see below |
| `poll_interval` | int | `5` | Poll interval in seconds, used by `poll` mode |

**Control Mode Comparison:**

| Mode | Behavior | Use Case |
|------|----------|----------|
| `explicit` | Only load models listed in `load_models` | Production, precise control |
| `poll` | Auto-detect repo changes, dynamically load/unload | Development |
| `none` | Load all available models in the repository | Quick validation |

#### `models` (Global Model Overrides)

The `models` field in `server.yaml` sets global defaults for specific models. Model-level `config.yaml` has higher priority.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | — | Model name (required) |
| `version` | str | `1` | Version number |
| `source` | str | `null` | Module path, used by CLI inline mode |
| `api_path` | str | `/predict` | Custom API path |
| `max_batch_size` | int | `1` | Max batch size, `1` disables batching |
| `batch_timeout` | float | `0.0` | Batch timeout in seconds |
| `stream` | bool | `false` | Enable streaming response |
| `accelerator` | str | `null` | Override global accelerator |
| `devices` | int/str | `null` | Override global device count |
| `workers_per_device` | int | `null` | Override global workers per device |

## Model Configuration (config.yaml)

Placed in `model_repo/{name}/{version}/config.yaml`, applies to the current version only.

```yaml
name: my_model
api_path: /predict
max_batch_size: 4
batch_timeout: 0.01
stream: false
accelerator: cpu
workers_per_device: 2
```

### Priority Rules

When the same field is defined in multiple places, priority from high to low:

1. **Version-level `config.yaml`** (highest priority)
2. **Model-level `model_config.yaml`** — loading policy and version strategy
3. **Global `server.yaml` `models` field**
4. **Global `server.yaml` `server` field** (defaults)

> See [Model Management](09_model_management.md) for details on `model_config.yaml`, version policies, and ensemble pipelines.

## Environment Variables

`model_repository.path` supports environment variable expansion:

```yaml
model_repository:
  path: "${HOME}/models"
```

## Configuration Validation

Validate configuration using the CLI:

```bash
light-server config-check server.yaml
```

## Next Steps

- [Model Development Guide](03_model_development.md)
- [CLI Reference](05_cli_reference.md)
