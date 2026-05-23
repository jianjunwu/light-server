# 01_quickstart — Hello World 智能文本增强

演示 light-server 最基本的用法：定义一个**有实际意义的 AI 模型**、启动服务、发送推理请求。

这个模型会分析输入文本的情绪（积极 / 消极 / 疑问 / 问候），并返回增强后的带 emoji 回复。**纯 Python 实现，零外部依赖。**

## 🎯 30 秒体验

```bash
cd examples/01_quickstart
./run.sh
```

终端会自动完成：检查依赖 → 验证模型逻辑 → 启动服务 → 发送测试请求 → 停止服务。

## 📸 运行效果

```
🔧 Step 1/4: 验证模型逻辑...
✅ Model logic test passed!

🚀 Step 2/4: 启动 light-server...
⏳ Step 3/4: 等待服务就绪...

🧪 Step 4/4: 发送推理请求...

--- 积极文本 ---
{
    "original": "I love this product",
    "enhanced": "I love this product ❤️ Absolutely amazing!",
    "mood": "positive"
}

--- 问候语 ---
{
    "original": "hello",
    "enhanced": "hello 👋 Welcome to light-server!",
    "mood": "greeting"
}

--- 中文输入 ---
{
    "original": "你好",
    "enhanced": "你好 😊 很高兴见到你！",
    "mood": "greeting"
}

✅ 所有测试通过！
```

## 手动运行

### 1. 启动服务

```bash
cd examples/01_quickstart
light-server serve --config server.yaml
```

### 2. 发送推理请求

```bash
# 英文积极
curl -X POST http://127.0.0.1:8000/v2/models/hello_model/infer \
  -H "Content-Type: application/json" \
  -d '{"text": "I love this product"}'

# 中文问候
curl -X POST http://127.0.0.1:8000/v2/models/hello_model/infer \
  -H "Content-Type: application/json" \
  -d '{"text": "你好"}'

# 疑问
curl -X POST http://127.0.0.1:8000/v2/models/hello_model/infer \
  -H "Content-Type: application/json" \
  -d '{"text": "How does this work?"}'
```

### 3. 管理 API

```bash
# 查看已加载模型
curl http://127.0.0.1:8000/v2/models

# 查看模型就绪状态
curl http://127.0.0.1:8000/v2/models/hello_model/ready

# 查看仓库中可用模型
curl -X POST http://127.0.0.1:8000/v2/repository/index
```

## 模型说明

- **`model.py`**：继承 `LitAPI`，实现情绪检测 + 文本增强逻辑
- **`config.yaml`**：单模型配置，`max_batch_size: 1` 表示不开启批处理
- **`server.yaml`**：服务端配置，关闭 gRPC 和指标，仅开启 HTTP

## 核心原理

```python
class HelloAPI(LitAPI):
    def decode_request(self, request):
        return request.get("text", "")

    def predict(self, text):
        mood = detect_mood(text)   # 关键词匹配检测情绪
        emoji = pick_emoji(mood)   # 根据情绪选 emoji
        reply = pick_reply(mood)   # 根据情绪选回复语
        return {"original": text, "enhanced": f"{text} {emoji} {reply}", "mood": mood}

    def encode_response(self, output):
        return output
```

## 下一步

👉 前往 [`07_batching_speedup`](../07_batching_speedup/)，体验自适应批处理带来的性能飞跃。
