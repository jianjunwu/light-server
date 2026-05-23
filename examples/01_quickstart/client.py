"""Interactive client for the hello model."""

import json
import sys

import requests


def infer(text: str) -> dict:
    resp = requests.post(
        "http://127.0.0.1:8000/v2/models/hello_model/infer",
        headers={"Content-Type": "application/json"},
        json={"text": text},
    )
    resp.raise_for_status()
    return resp.json()


def main():
    test_cases = [
        "hello",
        "I love this product",
        "How does this work?",
        "I am so sad today",
        "你好",
        "这是什么？",
    ]

    print("🧪 Hello Model Client\n")
    for text in test_cases:
        try:
            result = infer(text)
            mood_icon = {
                "positive": "😊",
                "negative": "😔",
                "question": "🤔",
                "greeting": "👋",
                "neutral": "😐",
            }.get(result["mood"], "📝")
            print(f"  Input:  {result['original']}")
            print(f"  Output: {result['enhanced']}")
            print(f"  Mood:   {mood_icon} {result['mood']}")
            print()
        except requests.exceptions.ConnectionError:
            print("❌ 无法连接到服务，请先启动 light-server")
            print("   light-server serve --config server.yaml")
            sys.exit(1)

    print("✅ 所有请求完成！")


if __name__ == "__main__":
    main()
