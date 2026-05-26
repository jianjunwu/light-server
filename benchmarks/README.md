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

| workers | concurrency | ls_rps | ls_p50 | ls_p90 | ls_p99 | lit_rps | lit_p50 | lit_p90 | lit_p99 |
|---------|-------------|--------|--------|--------|--------|---------|---------|---------|---------|
| 1       | 4           | 79.13  | 50.25  | 53.62  | 71.47  | 75.43   | 50.99   | 57.60   | 142.72  |
| 1       | 16          | 79.25  | 199.04 | 208.02 | 313.82 | 78.07   | 203.17  | 211.85  | 277.38  |
| 1       | 64          | 75.60  | 806.22 | 972.59 | 1260.0 | 74.67   | 825.81  | 978.85  | 1170.0  |
| 2       | 4           | 79.18  | 49.85  | 53.62  | 90.02  | 77.12   | 51.07   | 55.03   | 113.22  |
| 2       | 16          | 79.42  | 199.85 | 209.32 | 255.29 | 78.23   | 202.78  | 211.10  | 301.51  |
| 2       | 64          | 76.35  | 813.90 | 921.36 | 1080.0 | 77.87   | 819.41  | 842.72  | 913.54  |
| 4       | 4           | 79.54  | 49.69  | 53.56  | 74.36  | 74.48   | 51.19   | 63.00   | 118.85  |
| 4       | 16          | 77.38  | 200.24 | 232.28 | 318.30 | 73.71   | 207.88  | 252.21  | 336.21  |
| 4       | 64          | 79.32  | 795.26 | 821.62 | 967.41 | 76.36   | 821.06  | 891.57  | 993.12  |

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
