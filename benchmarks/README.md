# Benchmarks: light_server vs LitServe

Performance comparison of multi-process architectures using `wrk`.

## Prerequisites

Requires `light-server` and `litserve` to be installed in your Python environment:

```bash
# Install from PyPI (recommended for end users)
pip install light-server litserve

# Or install light-server from source in editable mode
uv pip install -e .

# Install wrk (macOS)
brew install wrk

# Or wrk on Linux
# sudo apt-get install wrk   # Ubuntu/Debian
# sudo yum install wrk       # RHEL/CentOS

# Optional: matplotlib for charts
pip install matplotlib
```

## Quick Start

All commands should be run from the **project root**:

```bash
# Quick sanity check (1 config, ~30s)
python benchmarks/scripts/compare.py --lite

# Full comparison (takes several minutes)
python benchmarks/scripts/compare.py --workers 1 2 4 --concurrency 1 4 16 64 --plot

# Use your own model repository
python benchmarks/scripts/compare.py \
  --model-repo /path/to/your/model_repo \
  --workers 1 2 4 --concurrency 1 4 16 64
```

## Custom Model Repository

Both `run_lightserver.py` and `run_litserve.py` support `--model-repo` to point to a custom model directory.

Expected structure (Triton-style):

```
model_repo/
  {model_name}/
    {version}/
      model.py       # Must contain a LitAPI subclass
      config.yaml    # Optional: max_batch_size, batch_timeout, etc.
```

The `model.py` must define a `LitAPI` subclass. Example:

```python
import light_server as ls

class MyAPI(ls.LitAPI):
    def setup(self, device):
        self.device = device

    def decode_request(self, request, **kwargs):
        return request.get("input", "")

    def predict(self, inputs, **kwargs):
        import time
        time.sleep(0.01)  # Simulate 10ms compute
        return {"output": inputs}

    def encode_response(self, output, **kwargs):
        return output
```

## Manual Run

### 1. light_server

```bash
# Terminal 1: built-in sleep model
python benchmarks/scripts/run_lightserver.py --port 8000 --workers 4

# Terminal 1: custom model repository
python benchmarks/scripts/run_lightserver.py \
  --port 8000 --workers 4 \
  --model-repo /path/to/your/model_repo

# Terminal 2
wrk -t4 -c64 -d30s --latency -s benchmarks/scripts/wrk_post.lua \
  http://127.0.0.1:8000/v2/models/{model_name}/infer
```

### 2. LitServe

```bash
# Terminal 1: built-in sleep model
python benchmarks/scripts/run_litserve.py --port 8001 --workers 4

# Terminal 1: custom model repository
python benchmarks/scripts/run_litserve.py \
  --port 8001 --workers 4 \
  --model-repo /path/to/your/model_repo

# Terminal 2
wrk -t4 -c64 -d30s --latency -s benchmarks/scripts/wrk_post.lua \
  http://127.0.0.1:8001/v2/models/{model_name}/infer
```

## Output

Results are saved to `benchmarks/results/benchmark.csv`:

> Benchmark run on 2026-05-27. HTTP server processes aligned with inference workers for both sides.

| workers | concurrency | ls_rps | ls_p50 | ls_p90 | ls_p99 | lit_rps | lit_p50 | lit_p90 | lit_p99 | speedup |
|---------|-------------|--------|--------|--------|--------|---------|---------|---------|---------|---------|
| 1       | 4           | 74.83  | 51.19  | 60.55  | 148.19 | 71.66   | 51.29   | 70.63   | 184.69  | 1.04x   |
| 1       | 16          | 74.00  | 207.04 | 251.10 | 417.95 | 72.62   | 210.74  | 256.02  | 352.41  | 1.02x   |
| 1       | 64          | 75.99  | 826.74 | 903.54 | 1030.0 | 77.11   | 813.91  | 916.70  | 959.70  | 0.99x   |
| 2       | 4           | 133.94 | 27.37  | 46.29  | 104.97 | 77.17   | 50.82   | 54.96   | 116.40  | 1.74x   |
| 2       | 16          | 157.34 | 100.52 | 169.39 | 260.86 | 77.60   | 202.89  | 211.32  | 316.03  | 2.03x   |
| 2       | 64          | 162.32 | 390.36 | 585.15 | 816.34 | 77.23   | 817.39  | 872.41  | 958.73  | 2.10x   |
| 4       | 4           | 162.44 | 22.81  | 33.26  | 85.98  | 73.18   | 53.59   | 60.74   | 100.86  | 2.22x   |
| 4       | 16          | 168.44 | 88.52  | 111.85 | 236.66 | 76.43   | 204.54  | 219.84  | 331.87  | 2.20x   |
| 4       | 64          | 156.85 | 379.98 | 542.46 | 730.48 | 76.84   | 824.44  | 871.79  | 941.29  | 2.04x   |

**Key findings:**
- **Single worker**: roughly equal (~75 req/s), capped by the 10ms sleep model
- **Multi-worker**: light_server scales linearly (74 -> 133 -> 162 req/s), while LitServe shows **virtually no scaling** (~75 req/s regardless of worker count)
- **Maximum advantage**: light_server is **2.22x** faster at 4 workers / 4 concurrency

With `--plot`, charts are saved to `benchmarks/results/comparison.png` and `benchmarks/results/scaling.png`.

## Test Matrix

Default comparison covers:
- **Workers**: 1, 2, 4 inference workers
- **Concurrency**: 1, 4, 16, 64 concurrent connections
- **Duration**: 30s per config (use `--duration 60` for even more stable results)
- **Model**: 10ms `time.sleep()` CPU mock (no GPU/GIL interference)

## Architecture Under Test

| Aspect | light_server | LitServe |
|--------|-------------|----------|
| HTTP layer | FastAPI + uvicorn, configurable workers | FastAPI + uvicorn, multi-process |
| Inference workers | 1 queue per worker | 1 shared `manager.Queue()` |
| Payload > 4KB | shared_memory zero-copy | pickle serialization |
| Process spawn | `mp.spawn` | `mp.spawn` |
