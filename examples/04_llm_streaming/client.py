"""WebSocket client for streaming LLM inference.

Usage:
    1. Start the server first:
       cd examples/04_llm_streaming && light-server serve --config server.yaml

    2. Run this script:
       python client.py
"""

import asyncio
import json

import websockets

BASE_URL = "ws://127.0.0.1:8000"


async def stream_generate(prompt: str, max_tokens: int = 20):
    """Connect via WebSocket and stream tokens from the LLM model."""
    uri = f"{BASE_URL}/v2/models/llm_model/stream"

    async with websockets.connect(uri) as ws:
        # Send generation request
        await ws.send(json.dumps({
            "prompt": prompt,
            "max_tokens": max_tokens,
        }))

        print(f"Prompt: {prompt}")
        print("Generated: ", end="", flush=True)

        token_count = 0
        async for message in ws:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                print(message, end="", flush=True)
                token_count += 1
                continue

            if "error" in data:
                print(f"\nError: {data['error']}")
                break

            token = data.get("token", "")
            print(token, end="", flush=True)
            token_count += 1

        print(f"\n\nTotal tokens: {token_count}")


async def main():
    prompts = [
        "Once upon a time",
        "The future of AI is",
        "Light Server provides",
    ]

    for prompt in prompts:
        print("=" * 60)
        await stream_generate(prompt, max_tokens=15)
        print()


if __name__ == "__main__":
    asyncio.run(main())
