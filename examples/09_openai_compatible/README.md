# 09_openai_compatible — OpenAI 格式适配

演示如何将 light-server 的推理响应**实时转换为 OpenAI Chat Completions 格式**。只需在你的应用中加一层薄适配，即可让 OpenAI SDK、LangChain、LlamaIndex 等生态工具直接调用 light-server 后端。

## 🎯 30 秒体验

```bash
cd examples/09_openai_compatible
./run.sh
```

终端会自动完成：验证模型 → 启动服务 → 发送请求 → 展示原生格式与 OpenAI 格式的对比。

## 📸 运行效果

```
🔗 OpenAI Format Adapter Demo

--- 1. Native light-server request/response ---
Native response:
{
  "original": "hello",
  "enhanced": "hello 👋 Welcome to light-server!",
  "mood": "greeting"
}

--- 2. Converted to OpenAI Chat Completions format ---
{
  "id": "chatcmpl-a3f2c1b8",
  "object": "chat.completion",
  "created": 1717000000,
  "model": "hello_model",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "hello 👋 Welcome to light-server!"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 1,
    "completion_tokens": 5,
    "total_tokens": 6
  }
}

--- 3. OpenAI Stream SSE chunks (for streaming) ---
data: {"id": "chatcmpl-...", "choices": [{"delta": {"content": "Hello"}}]}\n\n
data: {"id": "chatcmpl-...", "choices": [{"delta": {"content": "!"}}]}\n\n
data: {"id": "chatcmpl-...", "choices": [{"delta": {"content": " How"}}]}\n\n
data: [DONE]\n\n
✅ Your application can now use OpenAI SDK with light-server backend!
```

## 核心原理

### 格式转换函数

```python
def to_openai_format(native_response: dict, model_name: str = "hello_model") -> dict:
    """Convert light-server native response to OpenAI Chat Completions format."""
    return {
        "id": f"chatcmpl-{hash(...)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": native_response.get("enhanced", ""),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(native_response.get("original", "").split()),
            "completion_tokens": len(native_response.get("enhanced", "").split()),
            "total_tokens": ...,
        },
    }
```

### 流式 SSE Chunk

```python
def to_openai_stream_chunk(token: str, model_name: str = "hello_model") -> str:
    chunk = {
        "id": f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "delta": {"content": token},
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"
```

## 手动运行

### 1. 启动服务

```bash
cd examples/09_openai_compatible
light-server serve --config server.yaml
```

### 2. 运行适配演示

```bash
python client.py
```

## 集成到 OpenAI SDK

在你的应用中，只需将 `base_url` 指向一个轻量级适配代理：

```python
from openai import OpenAI

# 适配代理将 /v1/chat/completions 转发到 light-server
client = OpenAI(base_url="http://localhost:9000/v1", api_key="dummy")

response = client.chat.completions.create(
    model="hello_model",
    messages=[{"role": "user", "content": "hello"}],
)
print(response.choices[0].message.content)
```

适配代理的完整实现参考 `client.py` 中的 `to_openai_format()` 函数。

## 模型说明

- **`model.py`**：与 `01_quickstart` 相同的智能文本增强模型
- **`client.py`**：演示原生响应 → OpenAI 格式的转换逻辑
- 包含非流式和流式两种格式的转换示例
