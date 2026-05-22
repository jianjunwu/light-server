[English](../en/01_getting_started.md) | 简体中文

# 快速开始

## 安装

```bash
pip install light-server
```

需要 Python >= 3.10。

## 3 分钟跑通第一个模型

### 1. 创建模型仓库

```bash
mkdir -p model_repo/echo_model/1
```

在 `model_repo/echo_model/1/model.py` 中放置你的 LitAPI 子类：

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

在 `model_repo/echo_model/1/config.yaml` 中添加配置：

```yaml
name: echo_model
api_path: /predict
max_batch_size: 1
accelerator: cpu
```

### 2. 启动服务

创建 `server.yaml`：

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

启动：

```bash
light-server serve --config server.yaml
```

### 3. 发送推理请求

```bash
curl -X POST http://127.0.0.1:8000/v2/models/echo_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": "hello"}'
```

预期输出：

```json
{"output": "hello"}
```

## 目录结构

典型的项目结构：

```
my_project/
  server.yaml              # 服务配置
  model_repo/              # 模型仓库
    my_model/
      1/
        model.py           # LitAPI 子类
        config.yaml        # 模型配置（可选）
      2/
        model.py           # v2 版本
        config.yaml
```

## 下一步

- [配置详解](02_configuration.md)
- [模型开发指南](03_model_development.md)
- [examples/](../../examples/) 目录包含可直接运行的示例
