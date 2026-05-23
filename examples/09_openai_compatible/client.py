"""Demonstrate adapting light-server output to OpenAI Chat Completions format."""

import json
import time

import requests


def to_openai_format(native_response: dict, model_name: str = "llm_model") -> dict:
    """Convert light-server native response to OpenAI Chat Completions format."""
    return {
        "id": f"chatcmpl-{hash(native_response.get('original', '')) & 0xFFFFFFFF:08x}",
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
            "total_tokens": (
                len(native_response.get("original", "").split())
                + len(native_response.get("enhanced", "").split())
            ),
        },
    }


def to_openai_stream_chunk(token: str, model_name: str = "llm_model") -> str:
    """Convert a single token to OpenAI Chat Completions Stream SSE chunk."""
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


def main():
    print("🔗 OpenAI Format Adapter Demo\n")

    # 1. Native HTTP call to light-server
    print("--- 1. Native light-server request/response ---")
    resp = requests.post(
        "http://127.0.0.1:8000/v2/models/hello_model/infer",
        headers={"Content-Type": "application/json"},
        json={"text": "hello"},
    )
    native = resp.json()
    print(f"Native response:")
    print(json.dumps(native, indent=2, ensure_ascii=False))

    # 2. Convert to OpenAI format
    print("\n--- 2. Converted to OpenAI Chat Completions format ---")
    openai_fmt = to_openai_format(native)
    print(json.dumps(openai_fmt, indent=2, ensure_ascii=False))

    # 3. Show stream chunk format
    print("\n--- 3. OpenAI Stream SSE chunks (for streaming) ---")
    tokens = ["Hello", "!", " How", " can", " I", " help", "?"]
    for token in tokens:
        print(to_openai_stream_chunk(token), end="")
    print("data: [DONE]\n")

    print("✅ Your application can now use OpenAI SDK with light-server backend!")


if __name__ == "__main__":
    main()
