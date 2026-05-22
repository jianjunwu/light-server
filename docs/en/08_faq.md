[简体中文](../zh/08_常见问题.md) | English

# FAQ

## Deployment & Runtime

### Q: `ModuleNotFoundError` on macOS

**Cause**: macOS uses `spawn` mode for child processes by default; workers cannot inherit the parent process's module import state.

**Solution**: `light-server` handles this internally. Workers re-import `model.py` via `_inference_worker_wrapper`. Ensure:

1. Imports in `model.py` use absolute paths or sibling relative imports
2. No files in the model directory share names with Python standard library modules

### Q: Hot reload not working

**Checklist**:

1. `hot_reload: true` is set in `config.yaml`
2. `hot_reload_patterns` includes the file extension being modified (e.g. `*.py`)
3. You modified the `model.py` of the currently loaded version, not an unloaded one
4. Some editors use "atomic saves" (write temp file then rename), which may be missed

### Q: Port already in use

```
OSError: [Errno 48] Address already in use
```

**Solution**:

```bash
# Find process using the port
lsof -i :8000
# Or
kill $(lsof -t -i:8000)
```

Or change the port in `server.yaml`.

### Q: Can multiple models share GPU memory?

**Answer**: Yes. Weights loaded in `setup(self, device)` are shared within the same process among multiple workers (via intra-process sharing). However, different models use independent worker process groups, so memory is not shared across models. To share, put related models in the same `model.py` and expose them via different `api_path`s.

---

## Performance Tuning

### Q: How to determine optimal `max_batch_size`

**Suggestions**:

1. First run `light-server analyze` for automatic search
2. Manually test a few values (1, 2, 4, 8, 16) and observe throughput and latency
3. Consider GPU memory constraints

### Q: What `batch_timeout` value is appropriate?

**Principles**:

- Too short (< 0.001s): Batches are too small, batching advantage is minimal
- Too long (> 0.1s): Single request wait time increases, latency rises
- **Recommendation**: Start at 0.01s, adjust based on actual load

### Q: Throughput not increasing

**Troubleshooting**:

1. Check `workers_per_device`: typically 1 for GPU, can be increased for CPU
2. Check `max_batch_size`: too small to fully utilize hardware
3. Use the `benchmark` command to identify bottlenecks
4. Check if `predict` has blocking I/O

---

## Configuration

### Q: Which `control_mode` to choose

| Mode | When to Use |
|------|-------------|
| `explicit` | **Recommended for production**, precise control over loaded models |
| `poll` | Development, frequent model changes |
| `none` | Quick validation, load all models in repository |

### Q: How to override accelerator for a single model

Set in model-level `config.yaml`:

```yaml
accelerator: gpu
devices: 1
workers_per_device: 2
```

This takes priority over the global configuration in `server.yaml`.

---

## Artifact Packaging

### Q: What format is `.lma` file?

A ZIP archive containing `manifest.json` (metadata) and model files. Can be inspected with any ZIP tool.

### Q: Signature verification failed

```bash
# Check signature
light-server unpack artifact.lma --verify-key public.pem --dry-run

# If failed, possible causes:
# 1. Public key mismatch
# 2. File was tampered with
# 3. Packaged without signature but verification is required
```

---

## Next Steps

- [Configuration Guide](02_configuration.md)
- [Operations Guide](06_operations.md)
