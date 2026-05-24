# light-server 示例集

这里包含可直接运行的示例，帮助你快速掌握 light-server 的核心能力。

## 🚀 推荐学习路径

| 顺序 | 示例 | 预计耗时 | 你将学到 |
|------|------|---------|---------|
| 1️⃣ | [`01_quickstart`](01_quickstart/) | 30 秒 | 启动服务、发送推理请求、管理 API |
| 2️⃣ | [`02_advanced`](02_advanced/) | 1 分钟 | 进阶特性 — 批处理 + 自定义指标 + 热重载 + 版本管理 |
| 3️⃣ | [`03_cv_pipeline`](03_cv_pipeline/) | 2 分钟 | 真实 CV 多模型流水线（预处理 + ResNet） |
| 4️⃣ | [`04_llm_streaming`](04_llm_streaming/) | 1 分钟 | WebSocket 流式推理，逐 token 生成 |
| 5️⃣ | [`05_docker`](05_docker/) | 3 分钟 | Docker 容器化部署 |
| 6️⃣ | [`06_text_classification`](06_text_classification/) | 2 分钟 | 真实 NLP 模型 + 自适应批处理 |
| 7️⃣ | [`07_batching_speedup`](07_batching_speedup/) | 30 秒 | 自适应批处理如何让吞吐提升数倍 |
| 8️⃣ | [`08_grpc_client`](08_grpc_client/) | 30 秒 | gRPC 高性能调用，对比 HTTP REST 延迟 |
| 9️⃣ | [`09_openai_compatible`](09_openai_compatible/) | 30 秒 | 将响应实时转换为 OpenAI Chat Completions 格式 |
| 🔟 | [`10_ensemble_pipeline`](10_ensemble_pipeline/) | 30 秒 | DAG 多模型流水线编排、层内并行、层间串行 |
| 1️⃣1️⃣ | [`11_hooks_and_endpoints`](11_hooks_and_endpoints/) | 30 秒 | 模型生命周期 Hooks + 动态端点 — 请求/响应拦截 + 自定义路由 |

> 每个示例都包含 `./run.sh` 一键运行脚本，无需手动配置。

## 📂 按场景查找

### 刚接触 light-server
- [`01_quickstart`](01_quickstart/) — 最简上手，零外部依赖

### 性能调优
- [`07_batching_speedup`](07_batching_speedup/) — 批处理吞吐对比
- [`06_text_classification`](06_text_classification/) — 真实模型的批处理效果

### 真实 AI 模型
- [`03_cv_pipeline`](03_cv_pipeline/) — 图像分类（torchvision / TinyCNN）
- [`04_llm_streaming`](04_llm_streaming/) — 大语言模型流式生成
- [`06_text_classification`](06_text_classification/) — DistilBERT 情感分析

### 协议与生态
- [`08_grpc_client`](08_grpc_client/) — gRPC 调用与延迟对比
- [`09_openai_compatible`](09_openai_compatible/) — OpenAI 格式适配

### 流水线编排
- [`10_ensemble_pipeline`](10_ensemble_pipeline/) — DAG 多模型流水线、层内并行、层间串行

### 部署与运维
- [`02_advanced`](02_advanced/) — 版本管理、热重载、自定义指标
- [`05_docker`](05_docker/) — Dockerfile + docker-compose

### 扩展与定制
- [`11_hooks_and_endpoints`](11_hooks_and_endpoints/) — 模型级 Hooks（on_request / on_response / health_check）+ 动态端点注册

## 🏃 快速运行任意示例

```bash
cd examples/XX_name
./run.sh
```

`run.sh` 会自动完成：检查依赖 → 验证模型逻辑 → 启动服务 → 运行客户端 → 输出结果 → 停止服务。

## 📋 示例清单

| 示例 | 核心特性 | 外部依赖 |
|------|---------|---------|
| [`01_quickstart`](01_quickstart/) | HTTP 推理、管理 API | 无 |
| [`02_advanced`](02_advanced/) | 批处理、自定义指标、热重载、版本管理 | 无 |
| [`03_cv_pipeline`](03_cv_pipeline/) | 多模型 pipeline、图像预处理 + 分类 | `torch`, `torchvision`, `pillow` |
| [`04_llm_streaming`](04_llm_streaming/) | WebSocket 流式、逐 token 生成 | `websockets`（可选 transformers） |
| [`05_docker`](05_docker/) | 容器化部署 | Docker |
| [`06_text_classification`](06_text_classification/) | 真实 transformers 模型、批处理 | `transformers`, `torch` |
| [`07_batching_speedup`](07_batching_speedup/) | 自适应批处理、aiohttp 压测 | `aiohttp` |
| [`08_grpc_client`](08_grpc_client/) | gRPC 推理端点、延迟对比 | `grpcio` |
| [`09_openai_compatible`](09_openai_compatible/) | OpenAI 格式适配 | `requests` |
| [`10_ensemble_pipeline`](10_ensemble_pipeline/) | DAG 流水线编排、多模型并行串行 | 无 |
| [`11_hooks_and_endpoints`](11_hooks_and_endpoints/) | 模型生命周期 Hooks + 动态端点 | 无 |
