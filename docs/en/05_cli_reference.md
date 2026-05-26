[简体中文](../zh/05_CLI命令参考.md) | English

# CLI Reference

```
light-server [command] [options]
```

## Command Quick Reference

| Command | Description |
|---------|-------------|
| `serve` | Start the inference server |
| `config-check` | Validate a YAML configuration file |
| `benchmark` | Run performance benchmark against a running server |
| `analyze` | Run Model Analyzer to find optimal configuration |
| `pack` | Pack a model directory into a `.lma` artifact |
| `unpack` | Unpack a `.lma` artifact |
| `init` | Initialize a new project scaffold |

---

## serve

Start the inference server.

### Start with Configuration File

```bash
light-server serve --config server.yaml
```

### Start Inline Mode (No Config File)

```bash
light-server serve my_module:MyAPI --port 8000
```

> **Note:** Inline mode implicitly sets `control_mode` to `all`, which loads all available models from the repository. To load only specific models, use a config file with `control_mode: explicit` and `load_models`.

### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `module` | str | — | Python module path, format `module:Class` |
| `--config, -c` | str | — | Path to YAML configuration file |
| `--port` | int | `8000` | HTTP port |
| `--host` | str | `0.0.0.0` | Bind address |
| `--accelerator` | str | `auto` | Accelerator |
| `--devices` | str | `auto` | Number of devices |
| `--workers-per-device` | int | `1` | Workers per device |
| `--timeout` | float | `30.0` | Request timeout (seconds) |
| `--log-level` | str | `info` | Log level |
| `--log-dir` | str | — | Log directory (auto creates info.log + error.log) |
| `--log-info` | str | — | Info log file path |
| `--log-error` | str | — | Error log file path |
| `--log-format` | str | `json` | Log format: `json`/`text` |
| `--log-rotate-by` | str | `none` | Rotation strategy: `none`/`size`/`time` |
| `--log-max-size` | int | `100` | Max log file size in MB (size mode) |
| `--log-when` | str | `midnight` | Rotation interval (time mode) |
| `--log-backup-count` | int | `7` | Number of backup log files |
| `--model-repo` | str | `./model_repo` | Model repository path |
| `--grpc-port` | int | `8001` | gRPC port |
| `--metrics-port` | int | `8002` | Metrics port |
| `--http-workers` | int | `auto` | Number of HTTP worker processes (`auto` = `max(1, cpu_count() - 1)`) |
| `--no-grpc` | flag | — | Disable gRPC |
| `--no-metrics` | flag | — | Disable metrics |

---

## config-check

Validate configuration file syntax and fields.

```bash
light-server config-check server.yaml
```

Example output:

```
Configuration OK: server.yaml
  HTTP port: 8000
  gRPC port: 8001
  Metrics port: 8002
  Model repo: ./model_repo
  Load models: ['test_model']
```

---

## benchmark

Run benchmark against a running server.

```bash
light-server benchmark --model test_model --duration 30
```

### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--url` | str | `http://127.0.0.1:8000` | Server base URL |
| `--model` | str | **Required** | Model name |
| `--version` | str | `null` | Model version |
| `--concurrency` | int | `8` | Concurrent requests |
| `--duration` | float | `30.0` | Benchmark duration (seconds) |
| `--mode` | str | `fixed` | Load mode: `fixed`/`ramp` |
| `--max-concurrency` | int | `64` | Max concurrency for ramp mode |
| `--step-duration` | float | `10.0` | Seconds per ramp step |
| `--payload` | str | `'{"input": 1.0}'` | Request payload (JSON string) |
| `--output` | str | — | Results output JSON file |

### Output Example

```
Benchmark Results (test_model):
  Mode:            fixed
  Duration:        30s
  Total requests:  15000
  Success:         15000
  Failed:          0
  Throughput:      500.0 req/s
  Latency (ms):
    mean: 15.2
    p50:  14.0
    p90:  20.0
    p99:  35.0
    p99.9:50.0
```

---

## analyze

Run Model Analyzer to automatically search for optimal batch size, timeout, and concurrency.

```bash
light-server analyze --model test_model --output-dir ./reports
```

### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--model-repo` | str | `./model_repo` | Model repository path |
| `--model` | str | **Required** | Model name |
| `--output-dir` | str | `./reports` | Report output directory |

Output:

```
Analysis complete. Pareto optimal configurations: 12
```

Report saved to `./reports/{model_name}/analysis_report.json`.

---

## pack

Pack a model directory into a `.lma` (Light Model Artifact).

```bash
light-server pack model_repo/test_model --version 1.0.0
```

### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `model_dir` | str | **Required** | Model directory path |
| `--version, -v` | str | **Required** | Version (semver) |
| `--output, -o` | str | `./artifacts` | Output directory |
| `--build-id` | str | Auto-generated | Build ID |
| `--sign-key` | str | — | Path to Ed25519 private key PEM |
| `--signer` | str | — | Signer identity |
| `--ignore` | str | — | Additional ignore patterns (repeatable) |

---

## unpack

Unpack a `.lma` artifact.

```bash
light-server unpack artifact.lma --to ./model_repo
```

### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `artifact` | str | **Required** | Path to `.lma` file |
| `--to` | str | `.` | Target directory |
| `--verify-key` | str | — | Path to Ed25519 public key PEM |
| `--dry-run` | flag | — | Validate only, do not extract |

---

## init

Initialize a new project scaffold. Supports both interactive wizard and non-interactive modes.

### Interactive Mode

```bash
light-server init
```

Follow the wizard to select a template and configure gRPC / metrics / WebUI options. Automatically generates model code, config file, and Dockerfile.

### Non-interactive Mode

```bash
light-server init my_project --template llm --model-name my_llm
```

### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `project_name` | str | — | Project directory name (omit for interactive mode) |
| `--template, -t` | str | `empty` | Template: `empty` / `llm` / `cv-classify` / `cv-detect` / `nlp` |
| `--model-name, -m` | str | `my_model` | Model name |
| `--grpc` | flag | enabled | Enable gRPC |
| `--no-grpc` | flag | — | Disable gRPC |
| `--metrics` | flag | enabled | Enable metrics |
| `--no-metrics` | flag | — | Disable metrics |
| `--webui` | flag | enabled | Enable Web UI |
| `--no-webui` | flag | — | Disable Web UI |
| `--batch` | flag | — | Enable dynamic batching |
| `--stream` | flag | — | Enable streaming responses |
| `--output-dir, -o` | str | `.` | Project output directory |

---

## Next Steps

- [Operations Guide](06_operations.md)
- [FAQ](08_faq.md)
