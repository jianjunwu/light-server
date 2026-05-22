# 01_quickstart — 最简模型

演示 light-server 最基本的用法：定义模型、启动服务、发送推理请求、使用管理 API。

## 启动服务

```bash
cd examples/01_quickstart
light-server serve --config server.yaml
```

## 推理请求

```bash
curl -X POST http://127.0.0.1:8000/v2/models/echo_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": "hello world"}'
```

预期输出：

```json
{"output": "hello world"}
```

## 管理 API

```bash
# 查看已加载模型
curl http://127.0.0.1:8000/v2/models

# 查看模型就绪状态
curl http://127.0.0.1:8000/v2/models/echo_model/ready

# 查看仓库中可用模型
curl -X POST http://127.0.0.1:8000/v2/repository/index
```

## 模型说明

- `model.py`：继承 `LitAPI`，实现 `setup` / `decode_request` / `predict` / `encode_response`
- `config.yaml`：单模型配置，`max_batch_size: 1` 表示不开启批处理
- `server.yaml`：服务端配置，关闭 gRPC 和指标，仅开启 HTTP
