# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`light_server` is a Triton-style CLI deployment interface for LitServe. It provides a multi-port inference server with HTTP (inference + admin), gRPC, and Prometheus metrics endpoints, backed by a filesystem-based model repository with hot-load/unload support.

## Common Commands

```bash
# Development install (creates .venv automatically)
uv sync

# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_integration.py -v -s

# Start the server with config
uv run python -m light_server serve --config server.yaml

# Or via installed CLI
uv run light-server serve --config server.yaml

# Validate config
uv run light-server config-check server.yaml

# Add a dependency
uv add <package>

# Add a dev dependency
uv add --dev <package>
```

## High-Level Architecture

### Orchestration: `LightServer` (`core/server.py`)

`LightServer` is the top-level controller. It creates:
- An `mp.Manager()` for cross-process shared state
- A `ModelRegistry` backed by `mp.Manager().dict()`
- A shared `MPQueueTransport` (from LitServe) for worker-to-HTTP response communication
- A `ModelManager` that handles model loading/unloading
- HTTP (FastAPI + uvicorn), optional gRPC, and optional metrics servers

The HTTP server runs with `uvicorn(workers=1)` so that the single process can access the shared registry and response buffer directly.

### Model Repository Layout

Follows Triton convention:
```
model_repo/
  {model_name}/
    {version}/
      model.py       # Must contain a LitAPI subclass
      config.yaml    # Optional: max_batch_size, batch_timeout, etc.
```

### Model Loading (`core/model_manager.py`)

`ModelManager.load()`:
1. Dynamically imports `model.py` via `load_litapi_from_file()`
2. Instantiates the LitAPI in the parent process to validate it
3. Creates an `mp.Manager().Queue()` for request submission
4. Launches inference workers using `mp.get_context("spawn")`

**Critical spawn-safety pattern:** Workers do NOT receive LitAPI instances directly. Instead, `_inference_worker_wrapper` receives the `model_py_path` as a string and reconstructs the LitAPI inside the child process via `load_litapi_from_file(Path(model_py_path))`. This avoids `ModuleNotFoundError` when using `spawn` on macOS/Unix.

### Inference Flow (`http/handlers.py`)

1. HTTP handler receives request at `/v2/models/{model_name}/infer`
2. Calls `model_manager.infer()` which puts `(response_queue_id, uid, timestamp, payload)` onto the model's request queue
3. Handler creates an `asyncio.Event`, stores it in `server.response_buffer[uid]`, and awaits it
4. A background async task `_response_consumer()` continuously reads from `transport.areceive(consumer_id=0)`
5. When a response arrives, the consumer sets the event and the handler returns the JSON response

### Admin APIs (`http/admin.py`)

- `GET /v2/models` — list loaded models
- `GET /v2/models/{name}/ready` — readiness check
- `POST /v2/repository/index` — list available models in repo
- `POST /v2/repository/models/{name}/load` — load a model
- `POST /v2/repository/models/{name}/unload` — unload a model

### Configuration (`config.py`)

YAML-driven via `load_config()`. Key sections: `server`, `grpc`, `metrics`, `model_repository`, `load_models`. The `control_mode` field controls auto-loading behavior: `explicit` (load only `load_models`), `poll` (auto-detect repo changes), `none` (load all available).

## Key Files

| File | Purpose |
|------|---------|
| `src/light_server/core/server.py` | Main orchestrator |
| `src/light_server/core/model_manager.py` | Model load/unload/infer |
| `src/light_server/core/registry.py` | Cross-process model state |
| `src/light_server/core/loader.py` | Dynamic model.py import |
| `src/light_server/http/handlers.py` | Async inference + response consumer |
| `src/light_server/http/admin.py` | Admin routes |
| `src/light_server/config.py` | YAML config dataclasses |
| `src/light_server/cli.py` | CLI entry point |
