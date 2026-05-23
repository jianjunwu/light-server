# 07_batching_speedup — Batching 加速对比

演示 light-server 的**自适应批处理**如何将吞吐提升数倍。模型模拟 50ms 固定计算延迟，通过并发请求自动凑 batch，显著降低总耗时。

## 🎯 30 秒体验

```bash
cd examples/07_batching_speedup
./run.sh
```

终端会自动完成：验证模型 → 启动服务 → 并发发送 64 条请求 → 输出吞吐对比。

## 📸 运行效果

```
🚀 Sending 64 concurrent requests...

📊 Results
========================================
  Total requests:     64
  Total time:         ~0.35s
  Throughput:         ~180 req/s
  Avg latency:        ~5.5ms
  Batch sizes seen:   [1, 2, 4, 8, 16]
  Max batch size:     16
========================================

📈 Batching impact
  Without batching:   ~3.2s (64 × 50ms serial)
  With batching:      ~0.35s
  Speedup:            ~9×
```

## 核心原理

### 模型配置 (`config.yaml`)

```yaml
max_batch_size: 16      # 最多 16 条请求合并为一个 batch
batch_timeout: 0.05     # 最多等 50ms 凑 batch
```

### 服务端行为

当短时间内收到多条请求时，light-server 会：
1. 在 `batch_timeout` 窗口内收集请求
2. 凑够 `max_batch_size` 或超时后，合并为一个 list 传入 `predict()`
3. 模型一次计算处理整批，平摊延迟成本

### 客户端行为 (`client.py`)

使用 `asyncio` + `aiohttp` 并发发送 64 条请求：

```python
tasks = [send_one(session, i) for i in range(64)]
results = await asyncio.gather(*tasks)
```

## 手动运行

### 1. 启动服务

```bash
cd examples/07_batching_speedup
light-server serve --config server.yaml
```

### 2. 运行压测

```bash
pip install aiohttp
python client.py
```

### 3. 调整 batch 参数对比

编辑 `config.yaml` 尝试不同参数：

```yaml
# 小 batch — 延迟低但吞吐一般
max_batch_size: 4
batch_timeout: 0.01

# 大 batch — 吞吐高但单条延迟稍高
max_batch_size: 32
batch_timeout: 0.1
```

## 模型说明

- **`model.py`**：模拟固定 50ms 计算延迟的模型，返回平方计算结果和实际 batch 大小
- **`config.yaml`**：开启自适应批处理，`max_batch_size=16`
- **`client.py`**：并发压测客户端，输出吞吐和延迟统计

## 下一步

👉 前往 [`03_cv_pipeline`](../03_cv_pipeline/)，体验真实 CV 多模型流水线。
