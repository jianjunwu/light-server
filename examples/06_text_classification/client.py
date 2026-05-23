"""HTTP client for sentiment classification.

Usage:
    1. Start the server first:
       cd examples/06_text_classification && light-server serve --config server.yaml

    2. Run this script:
       python client.py
"""

import requests

BASE_URL = "http://127.0.0.1:8000"


def infer_single(text: str):
    """Send a single text for sentiment classification."""
    url = f"{BASE_URL}/v2/models/sentiment/infer"
    resp = requests.post(url, json={"text": text}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def infer_batch(texts: list[str]):
    """Send multiple texts in parallel (server batches them automatically)."""
    url = f"{BASE_URL}/v2/models/sentiment/infer"
    results = []
    for text in texts:
        resp = requests.post(url, json={"text": text}, timeout=30)
        resp.raise_for_status()
        results.append(resp.json())
    return results


def main():
    print("=" * 60)
    print("Single inference")
    print("=" * 60)

    single_texts = [
        "I love this product, it works amazingly well!",
        "This is the worst experience I've ever had.",
        "The weather is cloudy today.",
    ]

    for text in single_texts:
        result = infer_single(text)
        label = result.get("label", "N/A")
        score = result.get("score", 0.0)
        print(f"  [{label:8s} | {score:.4f}]  {text}")

    print()
    print("=" * 60)
    print("Batch inference (stress test)")
    print("=" * 60)

    batch_texts = [
        "Absolutely fantastic service!",
        "I hate waiting in long lines.",
        "The movie was okay, nothing special.",
        "Best purchase I've made this year!",
        "Terrible quality, broke after one day.",
        "Not bad, but could be better.",
    ]

    results = infer_batch(batch_texts)
    for text, result in zip(batch_texts, results):
        label = result.get("label", "N/A")
        score = result.get("score", 0.0)
        print(f"  [{label:8s} | {score:.4f}]  {text}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
