# light-server

English | [简体中文](README.md)

<p align="center">
  <strong>As simple as a Flask API, as production-ready as Triton</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/light-server/"><img src="https://img.shields.io/pypi/v/light-server.svg" alt="PyPI"></a>
  <a href="https://pypi.org/project/light-server/"><img src="https://img.shields.io/pypi/pyversions/light-server.svg" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
</p>

`light-server` is a Triton-style CLI deployment interface for [LitServe](https://github.com/Lightning-AI/litserve). It provides a multi-port inference server with HTTP (inference + admin), gRPC, and Prometheus metrics endpoints, backed by a filesystem-based model repository with hot-load/unload support.

```mermaid
graph LR
    A[Client] -->|HTTP / gRPC / WebSocket| B[LightServer]
    B --> C[Model Registry]
    B --> D[Inference Workers]
    C --> E[Filesystem Model Repo]
    D --> F[LitAPI Model]
    B --> G[Prometheus Metrics]
    B --> H[Web UI]
```

## Why light-server?

| | light-server | LitServe | Triton | vLLM | BentoML |
|---|---|---|---|---|---|
| **Positioning** | Lightweight multi-framework inference server | Python inference library | Full-featured inference platform | LLM only | Full-stack MLOps |
| **Learning curve** | One command to start | Requires server code | Requires build/complex config | Needs GPU scheduling knowledge | Steep learning curve |
| **Model frameworks** | PyTorch/TF/ONNX/any Python | PyTorch/any Python | TensorRT/ONNX/PyTorch | LLM only | Multiple backends |
| **Protocols** | HTTP + gRPC + WebSocket + metrics | HTTP only | HTTP + gRPC + many protocols | HTTP + OpenAI API | HTTP + gRPC |
| **Model management** | Filesystem repo + hot load/unload | None | Model repo + versioning | Single model service | Bento repo |
| **Batching** | Adaptive batching + Continuous Batching | Adaptive batching | Dynamic batching | Continuous Batching | Requires config |
| **Resource usage** | Lightweight, single process | Lightweight | Heavy, multi-service | GPU intensive | Medium |
| **Best for** | Small-to-medium inference, rapid iteration | Quick prototyping / single model | Large-scale production clusters | LLM inference | End-to-end MLOps |

**The core value of light-server**: If you need a server that can serve multiple models (not just LLMs), supports hot updates, has monitoring metrics, and is quick to get started, light-server is lighter than Triton and more general-purpose than vLLM. It adds model repository management, multi-protocol serving, and operational capabilities on top of [LitServe](https://github.com/Lightning-AI/litserve).

## Features

- **Multi-protocol serving**: HTTP REST, gRPC, and Prometheus metrics on separate ports; WebSocket for bidirectional streaming
- **Triton-style model repository**: filesystem-based layout with versioned models
- **Hot load/unload**: load and unload models via admin APIs without restarting the server
- **Batching & streaming**: adaptive batching + Continuous Batching; configure `max_batch_size`, `batch_timeout`, streaming, and Continuous Batching per model
- **Model Analyzer**: automatically find optimal batch size / timeout / concurrency configurations
- **Benchmark tool**: built-in HTTP benchmark with latency percentiles (p50/p90/p99/p99.9)
- **Artifact packaging**: pack/unpack models into signed `.lma` artifacts for deployment
- **Structured logging**: JSON/text output with size/time-based rotation
- **Web UI**: built-in web interface for model management and observability

## 30-Second Quickstart

```bash
pip install light-server
light-server init my_project && cd my_project
light-server serve --config server.yaml
# In another terminal
curl -X POST http://127.0.0.1:8000/v2/models/my_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": "hello"}'
```

## Install

```bash
pip install light-server
```

Requires Python >= 3.10.

### Development from Source

This project uses [uv](https://docs.astral.sh/uv/) for dependency management:

```bash
# Clone and sync dependencies
uv sync

# Run tests
uv run pytest tests/ -v

# Start the server (development mode)
uv run light-server serve --config server.yaml
```

## Quick Start

### Option 1: Project Scaffolding (Recommended)

```bash
light-server init my_project
```

Follow the wizard to choose a template. Project code, Dockerfile, and CI config are generated automatically.

### Option 2: Manual

#### 1. Create a model repository

```bash
mkdir -p model_repo/test_model/1
```

Place your LitAPI subclass in `model_repo/test_model/1/model.py`:

```python
from light_server import LitAPI

class MyAPI(LitAPI):
    def setup(self, device):
        self.model = lambda x: x * 2

    def decode_request(self, request):
        return request["input"]

    def predict(self, x):
        return self.model(x)

    def encode_response(self, output):
        return {"result": output}
```

Optionally add `model_repo/test_model/1/config.yaml`:

```yaml
max_batch_size: 4
batch_timeout: 0.01
stream: false
```

Continuous Batching configuration (for LLM token-by-token generation):

```yaml
max_batch_size: 8          # max concurrent sequences
stream: true               # Continuous Batching requires streaming
continuous_batching: true
max_sequence_length: 2048
```

#### 2. Start the server

```bash
light-server serve --config server.yaml
```

Example `server.yaml`:

```yaml
server:
  host: 127.0.0.1
  http_port: 8000
  grpc_port: 8001
  metrics_port: 8002
  log_level: info

grpc:
  enabled: true

metrics:
  enabled: true

model_repository:
  path: ./model_repo
  control_mode: explicit

load_models:
  - test_model
```

Or start inline without a config file:

```bash
light-server serve my_module:MyAPI --port 8000
```

#### 3. Send an inference request

```bash
curl -X POST http://127.0.0.1:8000/v2/models/test_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": 5.0}'
```

#### 4. Admin APIs

```bash
# List loaded models
curl http://127.0.0.1:8000/v2/models

# Load a model
curl -X POST http://127.0.0.1:8000/v2/repository/models/my_model/load

# Unload a model
curl -X POST http://127.0.0.1:8000/v2/repository/models/my_model/unload
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize project scaffolding (model code, Dockerfile, CI config) |
| `serve` | Start the inference server |
| `config-check` | Validate a YAML configuration file |
| `benchmark` | Run performance benchmark against a running server |
| `analyze` | Run Model Analyzer to find optimal configuration |
| `pack` | Pack a model directory into a `.lma` artifact |
| `unpack` | Unpack a `.lma` artifact |

```bash
# Initialize project
light-server init my_project

# Validate configuration
light-server config-check server.yaml

# Benchmark a model
light-server benchmark --model test_model --duration 30

# Analyze model for optimal config
light-server analyze --model test_model --output-dir ./reports

# Pack a model for deployment
light-server pack model_repo/test_model --version 1.0.0

# Unpack a deployed artifact
light-server unpack artifact.lma --to ./model_repo
```

## Model Repository Layout

Follows the Triton convention:

```
model_repo/
  text_classifier/           # model name
    1/                       # version (numeric string)
      model.py               # must contain a LitAPI subclass
      config.yaml            # optional: version-level config
    2/
      model.py
      config.yaml
  image_detector/
    1/
      model.py
      config.yaml
```

### `config.yaml` Fields

Each version's `config.yaml` supports the following fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_batch_size` | int | `1` | Max batch size; `1` disables batching |
| `batch_timeout` | float | `0.0` | Batching timeout in seconds; `0.0` means no timeout |
| `stream` | bool | `false` | Enable streaming responses |
| `continuous_batching` | bool | `false` | Enable Continuous Batching (LLM token-by-token generation) |
| `max_sequence_length` | int | — | Max sequence length for Continuous Batching |
| `workers_per_device` | int | `1` | Workers per device |
| `timeout` | float | `30.0` | Per-request timeout in seconds |
| `accelerator` | str | `auto` | Accelerator: `auto` / `cpu` / `gpu` / `mps` |

### Key Rules

- **`model.py` requirement**: Each `model.py` must contain exactly one `LitAPI` subclass. The server dynamically imports and loads it automatically.
- **Version naming**: Version directory names must be numeric strings (e.g. `1`, `2`). Non-numeric names like `v1` are not supported. The largest numeric version is loaded by default.
- **Config scope**: `config.yaml` is **version-level** configuration. Different versions of the same model can have independent batch sizes, timeouts, accelerators, etc.
- **Quick scaffold**: Use `light-server init my_project` to automatically generate a model repository that follows this layout with default config.

## Configuration

See `server.yaml` for a full example. Key sections:

- `server`: HTTP/gRPC/metrics ports, host, accelerator, timeout, log level, number of API workers
- `grpc`: enable/disable gRPC endpoint, `max_workers`
- `metrics`: enable/disable Prometheus metrics
- `model_repository`: repository path and control mode (`explicit`, `poll`, `none`)
- `load_models`: list of models to auto-load on startup
- `models`: per-model overrides (batch size, streaming, accelerator, etc.)
- `logging`: log mode, format, output path, rotation policy
- `webui`: built-in web interface settings

For a full field reference, see [Configuration Details](docs/en/02_configuration_details.md).

## Documentation

Detailed documentation is in the [`docs/en/`](docs/en/) directory:

| Document | Content |
|----------|---------|
| [Quick Start](docs/en/01_quick_start.md) | Installation + 3-minute getting started |
| [Configuration Details](docs/en/02_configuration_details.md) | Full field reference + priority rules |
| [Model Development Guide](docs/en/03_model_development_guide.md) | LitAPI lifecycle + batching/streaming/metrics/versioning |
| [API Reference](docs/en/04_api_reference.md) | HTTP/gRPC endpoints + status codes |
| [CLI Command Reference](docs/en/05_cli_command_reference.md) | Full arguments for 7 subcommands |
| [Operations Guide](docs/en/06_operations_guide.md) | Prometheus + logging + artifact packaging + analyzer + WebUI |
| [Architecture Design](docs/en/07_architecture_design.md) | Process model + request flow + Mermaid diagrams |
| [FAQ](docs/en/08_faq.md) | Common questions and performance tuning |

Chinese documentation is in [`docs/zh/`](docs/zh/).

## Architecture

- **`LightServer`** (`core/server.py`): top-level orchestrator, creates registry, transport, and servers
- **`ModelManager`** (`core/model_manager.py`): handles dynamic model loading/unloading via `mp.spawn`
- **`ModelRegistry`** (`core/registry.py`): cross-process shared state via `mp.Manager().dict()`
- **HTTP handlers** (`http/handlers.py`): async inference with response consumer pattern
- **Admin APIs** (`http/admin.py`): model lifecycle and readiness checks

## Examples

See the [`examples/`](examples/) directory for runnable examples:

| Example | Description |
|---------|-------------|
| [`01_quickstart`](examples/01_quickstart/) | Smart text enhancement — serve, infer, admin APIs |
| [`02_advanced`](examples/02_advanced/) | Advanced features — batching + custom metrics + hot reload + versioning |
| [`03_cv_pipeline`](examples/03_cv_pipeline/) | Real CV pipeline — image preprocessing + ResNet classification |
| [`04_llm_streaming`](examples/04_llm_streaming/) | LLM streaming inference — WebSocket token-by-token generation |
| [`05_docker`](examples/05_docker/) | Docker containerized deployment — Dockerfile + docker-compose |
| [`06_text_classification`](examples/06_text_classification/) | Real NLP classification — DistilBERT sentiment analysis + adaptive batching |
| [`07_batching_speedup`](examples/07_batching_speedup/) | Batching speedup comparison — data-driven throughput gains |
| [`08_grpc_client`](examples/08_grpc_client/) | gRPC high-performance calls — latency comparison vs HTTP REST |
| [`09_openai_compatible`](examples/09_openai_compatible/) | OpenAI format adapter — real-time response transformation |
| [`10_ensemble_pipeline`](examples/10_ensemble_pipeline/) | DAG multi-model pipeline orchestration — intra-layer parallelism, inter-layer serial |
| [`11_hooks_and_endpoints`](examples/11_hooks_and_endpoints/) | Model lifecycle hooks + dynamic endpoints — request/response interception + custom routes |

Each example includes a `run.sh` one-shot script and `test_model.py` for standalone model validation.

## License

MIT
