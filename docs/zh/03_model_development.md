[English](../en/03_model_development.md) | 简体中文

# 模型开发指南

## 模型仓库规范

遵循 Triton 风格布局：

```
model_repo/
  {model_name}/
    {version}/
      model.py       # 必须包含 LitAPI 子类
      config.yaml    # 可选：max_batch_size, batch_timeout 等
```

- `model_name`：模型目录名，在管理 API 和推理端点中作为标识
- `version`：版本号字符串（如 `1`、`2`、`v1.0`），支持多版本并存
- `model.py`：必须包含一个继承自 `LitAPI` 的类

## LitAPI 生命周期

```python
from light_server import LitAPI

class MyAPI(LitAPI):
    def setup(self, device):
        """初始化模型、加载权重。device 由 light-server 分配。"""
        self.model = load_model()

    def decode_request(self, request, **kwargs):
        """将 HTTP JSON 请求解析为 predict 可处理的输入。"""
        return request["input"]

    def predict(self, x, **kwargs):
        """执行推理。当 batching 启用时，x 为列表。"""
        return self.model(x)

    def encode_response(self, output, **kwargs):
        """将 predict 的输出编码为 JSON 响应。"""
        return {"result": output}
```

### 方法说明

| 方法 | 触发时机 | 说明 |
|------|----------|------|
| `setup(device)` | Worker 进程启动时 | 每个 worker 独立调用一次，`device` 为分配的加速器 |
| `decode_request(request, **kwargs)` | 每个请求 | 解析 HTTP 请求体为模型输入 |
| `predict(x, **kwargs)` | 每个请求/批次 | 执行实际推理 |
| `encode_response(output, **kwargs)` | 每个请求 | 编码为 JSON 返回给客户端 |

### setup 中的配置读取

```python
def setup(self, device):
    # 从 config.yaml 读取自定义字段
    self.max_length = self.config.get("max_length", 512)
    self.threshold = self.config.get("threshold", 0.5)
    self.logger.info(f"max_length={self.max_length}")
```

`self.config` 是 `config.yaml` 解析后的字典，`self.logger` 是结构化日志记录器。

## 批处理（Batching）

### 开启批处理

在 `config.yaml` 中设置：

```yaml
max_batch_size: 8
batch_timeout: 0.01
```

### predict 中的批处理路径

```python
def predict(self, x, **kwargs):
    if isinstance(x, list):
        # 批处理路径：x = [input1, input2, ...]
        return [self.model(item) for item in x]
    # 单条路径
    return self.model(x)
```

### 调优建议

| 场景 | max_batch_size | batch_timeout |
|------|---------------|---------------|
| 高并发、延迟敏感 | 4-8 | 0.001-0.01s |
| 吞吐优先 | 16-32 | 0.05-0.1s |
| GPU 显存受限 | 2-4 | 0.01s |

## 流式响应（Streaming）

### 开启流式

```yaml
stream: true
```

### predict 返回生成器

```python
def predict(self, x, **kwargs):
    for token in self.model.generate(x):
        yield token
```

`encode_response` 会逐块接收 `yield` 的值并流式返回给客户端。

## 自定义 Prometheus 指标

```python
from prometheus_client import Counter, Histogram

class MyAPI(LitAPI):
    request_counter = Counter("my_requests_total", "Total requests")
    latency = Histogram("my_latency_seconds", "Latency", buckets=[0.001, 0.01, 0.1, 1.0])

    def predict(self, x, **kwargs):
        self.request_counter.inc()
        with self.latency.time():
            return self.model(x)
```

指标自动通过 multiproc 模式聚合，可在 `:metrics_port/metrics` 查看。

## 版本控制

### 多版本并存

```
model_repo/
  my_model/
    1/
      model.py
      config.yaml
    2/
      model.py
      config.yaml
```

### 切换版本

```bash
# 加载指定版本
curl -X POST http://127.0.0.1:8000/v2/repository/models/my_model/load \
  -H "Content-Type: application/json" \
  -d '{"version": "2"}'

# 查看活跃版本
curl http://127.0.0.1:8000/v2/models/my_model
```

### 热重载

在 `config.yaml` 中启用：

```yaml
hot_reload: true
hot_reload_interval: 1.0
hot_reload_patterns:
  - "*.py"
  - "*.yaml"
```

修改 `model.py` 或 `config.yaml` 后自动重新加载，无需重启服务。

## 辅助模块

`model.py` 同级目录下的 `.py` 文件可被导入：

```python
# model_repo/my_model/1/utils.py
def preprocess(x):
    return x.lower()

# model_repo/my_model/1/model.py
import utils

def decode_request(self, request, **kwargs):
    return utils.preprocess(request["text"])
```

## 下一步

- [API 参考](04_api_reference.md)
- [进阶示例：批处理 + 指标 + 热重载](../../examples/02_advanced/)
