# 04_llm_streaming — LLM 流式推理

演示 light-server 的 WebSocket 流式推理能力：模型逐 token 生成文本，客户端实时接收并显示，形成"打字机"效果。

## 目录结构

```
model_repo/
  llm_model/           # 大语言模型（流式生成）
    1/
      model.py         # 逐 token yield 的 LitAPI
      config.yaml      # stream=true, bidirectional=true
server.yaml            # 服务端配置
client.py              # WebSocket 流式客户端
run.sh                 # 一键运行
```

## 🎯 30 秒体验

```bash
cd examples/04_llm_streaming
./run.sh
```

终端会自动完成：验证模型逻辑 → 启动服务 → 运行 WebSocket 流式客户端 → 停止服务。

## 📸 运行效果

```
🔧 Step 1/4: 验证模型逻辑...
✅ Model logic test passed!

🚀 Step 2/4: 启动 light-server...
⏳ Step 3/4: 等待服务就绪...

🧪 Step 4/4: 运行 WebSocket 流式客户端...

============================================================
Prompt: Once upon a time
Generated: Once upon a time , there was a young girl who
loved to explore the world around her . She would spend
hours wandering through the forests and meadows ...

Total tokens: 32
============================================================
Prompt: The future of AI is
Generated: The future of AI is bright and full of
possibilities . With continued research and development ,
we can expect to see even more innovative applications ...

Total tokens: 28
============================================================
```

## 启动服务

```bash
cd examples/04_llm_streaming
light-server serve --config server.yaml
```

## 运行客户端

```bash
python client.py
```

客户端会依次发送 3 个 prompt，每个 prompt 的生成结果会逐词实时显示在终端上。

## 核心原理

### 模型端（model.py）

`predict()` 方法返回一个 **generator**，每次 `yield` 一个 token：

```python
def predict(self, x, **kwargs):
    for i in range(x["max_tokens"]):
        token = generate_next_token(...)
        yield {"token": token}
```

### 配置端（config.yaml）

必须开启流式和双向模式：

```yaml
stream: true
bidirectional: true
```

### 客户端（client.py）

通过 WebSocket 连接 `/v2/models/llm_model/stream`，发送 prompt 后持续接收消息：

```python
async with websockets.connect(uri) as ws:
    await ws.send(json.dumps({"prompt": "hello", "max_tokens": 20}))
    async for message in ws:
        data = json.loads(message)
        print(data["token"], end="", flush=True)
```

## 使用真实 transformers 模型

默认示例使用 mock 生成器以便一键运行。如需接入真实 LLM：

1. 安装依赖：
   ```bash
   pip install transformers torch
   ```

2. 编辑 `model_repo/llm_model/1/model.py`，取消底部的 transformers 版本注释，并删除上方的 mock 版本。

3. 支持 `gpt2`、`distilgpt2` 或其他 `AutoModelForCausalLM` 兼容模型。

## 扩展思路

- **接入 vLLM**：在 `setup()` 中初始化 vLLM 的 `LLM` 实例，`predict()` 中调用 `llm.generate(...)` 并 yield 每个输出 token
- **多轮对话**：客户端发送 `{"messages": [...]}`，模型维护对话历史上下文
- **SSE 替代 WebSocket**：如需 HTTP SSE，可扩展 handlers 添加 `/v2/models/{name}/stream-sse` 端点
