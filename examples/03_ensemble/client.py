"""Client-side pipeline for the ensemble example.

Usage:
    1. Start the server first:
       cd examples/03_ensemble && light-server serve --config server.yaml

    2. Run this script:
       python client.py
"""

import requests

BASE_URL = "http://127.0.0.1:8000"


def sentiment_analysis(text: str) -> dict:
    """Run the full preprocess -> predict pipeline."""
    # Step 1: preprocess
    r1 = requests.post(
        f"{BASE_URL}/v2/models/preprocess/infer",
        json={"text": text},
    )
    r1.raise_for_status()
    tokens = r1.json()["tokens"]

    # Step 2: predict
    r2 = requests.post(
        f"{BASE_URL}/v2/models/predict/infer",
        json={"tokens": tokens},
    )
    r2.raise_for_status()
    return r2.json()


def main():
    examples = [
        "I love this wonderful movie",
        "I hate this terrible movie",
        "This is a GREAT day and I love it",
        "The weather is okay today",
    ]

    print("=" * 60)
    print("Sentiment Analysis Pipeline Demo")
    print("=" * 60)

    for text in examples:
        result = sentiment_analysis(text)
        print(f"\nInput:  {text}")
        print(f"Result: {result}")


if __name__ == "__main__":
    main()
