[English](../en/06_operations.md) | 简体中文

# 运维指南

## Prometheus 指标

### 启用指标

```yaml
metrics:
  enabled: true
```

指标端点：`http://{host}:{metrics_port}/metrics`，默认 `http://127.0.0.1:8002/metrics`。

### 内置指标

| 指标名 | 类型 | 说明 |
|--------|------|------|
| `litserve_request_duration_seconds` | Histogram | 请求处理延迟 |
| `litserve_requests_total` | Counter | 总请求数 |
| `litserve_active_requests` | Gauge | 活跃请求数 |

### 自定义指标

在模型中定义：

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

自定义指标自动通过 multiproc 模式聚合。

---

## 日志

### 日志模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `queue` | 异步队列写入 | 高并发，默认 |
| `file` | 直接文件写入 | 简单场景 |

### 日志配置

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

### 格式

**JSON 格式（默认）：**

```json
{"timestamp":"2024-01-01T12:00:00","level":"INFO","message":"Model loaded","model":"test_model"}
```

**Text 格式：**

```
2024-01-01 12:00:00 [INFO] Model loaded: test_model
```

### 在模型中使用日志

```python
def predict(self, x, **kwargs):
    self.logger.info(f"predict called with input={x}")
    self.logger.warning("Something unexpected")
    return self.model(x)
```

---

## 制品打包（Artifact）

### 打包模型

```bash
light-server pack model_repo/test_model --version 1.0.0
```

输出：`artifacts/test_model-1.0.0-{build_id}.lma`

`.lma` 文件是一个 ZIP 压缩包，包含：

- `manifest.json`：元数据（名称、版本、构建 ID、文件列表、哈希）
- 模型文件

### 签名（可选）

```bash
light-server pack model_repo/test_model --version 1.0.0 --sign-key private.pem --signer "ci@company.com"
```

### 解包

```bash
light-server unpack artifact.lma --to ./model_repo
```

### 校验

```bash
light-server unpack artifact.lma --verify-key public.pem --dry-run
```

---

## 模型分析器

分析器自动搜索最优配置组合：

```bash
light-server analyze --model test_model --output-dir ./reports
```

搜索空间：

- `max_batch_size`：1, 2, 4, 8, 16
- `batch_timeout`：0.001, 0.01, 0.1
- `concurrency`：1, 2, 4, 8, 16

报告输出：

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

Pareto 前沿上的配置是在吞吐量和延迟之间取得最佳平衡的点。

---

## Web UI

### 启用

```yaml
webui:
  enabled: true
```

### 访问

打开浏览器访问 `http://{host}:{http_port}/`。

### 功能

- 查看已加载模型列表和状态
- 实时查看 Prometheus 指标图表
- 模型加载/卸载操作
- 推理请求测试界面
- 分析器报告查看

---

## 下一步

- [架构设计](07_architecture.md)
- [FAQ](08_faq.md)
