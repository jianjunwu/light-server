# 05_docker — Docker 容器化部署

演示如何将 light-server 服务打包为 Docker 镜像，并通过 docker-compose 部署。

## 目录结构

```
model_repo/
  demo_model/
    1/
      model.py      # 情感分类模型
      config.yaml   # 模型配置（开启 batching）
server.yaml         # 服务端配置
docker-compose.yml  # 容器编排
Dockerfile          # 镜像构建
```

## 🎯 30 秒体验

```bash
cd examples/05_docker
./run.sh
```

> 本地预览模式（不依赖 Docker）。完整 Docker 部署见下方。

## 📸 运行效果

```
🔧 Step 1/4: 验证模型逻辑...
✅ Model logic test passed!

🚀 Step 2/4: 启动 light-server (本地模式)...
⏳ Step 3/4: 等待服务就绪...

🧪 Step 4/4: 发送推理请求...

--- 推理请求 ---
{
    "sentiment": "positive",
    "score": 0.286,
    "positive_words": 2,
    "negative_words": 0
}

--- Prometheus 指标 ---
lightserver_inference_duration_seconds_bucket{model="demo_model",le="0.01"} 1

🛑 停止服务...
✅ 完成！

💡 Docker 部署: docker-compose up --build
```

## 快速开始

### 1. 构建并启动

```bash
cd examples/05_docker
docker-compose up --build
```

### 2. 发送推理请求

```bash
curl -X POST http://127.0.0.1:8000/v2/models/demo_model/infer \
  -H "Content-Type: application/json" \
  -d '{"text": "This is a great and amazing product"}'
```

预期输出：

```json
{"sentiment": "positive", "score": 0.286, "positive_words": 2, "negative_words": 0}
```

### 3. 查看指标

```bash
curl http://127.0.0.1:8002/metrics
```

### 4. 停止服务

```bash
docker-compose down
```

## 生产建议

- **镜像大小**：基于 `python:3.11-slim`，如需进一步缩小可使用多阶段构建
- **模型热更新**：通过 `volumes` 挂载 `model_repo`，修改模型文件后重启容器即可生效
- **健康检查**：docker-compose 中已配置 `healthcheck`，可配合负载均衡使用
- **日志**：容器内日志输出到 stdout，由 Docker 收集；如需文件日志，在 `server.yaml` 中配置 `logging`
