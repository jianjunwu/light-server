[简体中文](../zh/01_getting_started.md) | English

# Getting Started

## Installation

```bash
pip install light-server
```

Requires Python >= 3.10.

## Run Your First Model in 3 Minutes

### 1. Create a Model Repository

```bash
mkdir -p model_repo/echo_model/1
```

Place your LitAPI subclass in `model_repo/echo_model/1/model.py`:

```python
from light_server import LitAPI

class EchoAPI(LitAPI):
    def setup(self, device):
        pass

    def decode_request(self, request, **kwargs):
        return request.get("input", "")

    def predict(self, x, **kwargs):
        return x

    def encode_response(self, output, **kwargs):
        return {"output": output}
```

Add model configuration in `model_repo/echo_model/1/config.yaml`:

```yaml
name: echo_model
api_path: /predict
max_batch_size: 1
accelerator: cpu
```

### 2. Start the Server

Create `server.yaml`:

```yaml
server:
  host: 127.0.0.1
  http_port: 8000
  log_level: info

grpc:
  enabled: false

metrics:
  enabled: false

model_repository:
  path: ./model_repo
  control_mode: explicit

load_models:
  - echo_model
```

Start:

```bash
light-server serve --config server.yaml
```

### 3. Send an Inference Request

```bash
curl -X POST http://127.0.0.1:8000/v2/models/echo_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": "hello"}'
```

Expected output:

```json
{"output": "hello"}
```

## Directory Structure

A typical project layout:

```
my_project/
  server.yaml              # Server configuration
  model_repo/              # Model repository
    my_model/
      1/
        model.py           # LitAPI subclass
        config.yaml        # Model config (optional)
      2/
        model.py           # Version 2
        config.yaml
```

## Next Steps

- [Configuration Guide](02_configuration.md)
- [Model Development Guide](03_model_development.md)
- [examples/](../../examples/) directory contains runnable examples
