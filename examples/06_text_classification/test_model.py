"""Validate the sentiment model logic without starting the server."""

import sys

sys.path.insert(0, "./model_repo/sentiment/1")

from model import SentimentAPI


def test_single():
    api = SentimentAPI()
    api.setup("cpu")

    request = {"text": "This is absolutely amazing!"}
    decoded = api.decode_request(request)
    assert decoded == "This is absolutely amazing!"

    result = api.predict([decoded])[0]
    assert "label" in result
    assert "score" in result
    assert result["label"] == "POSITIVE"
    assert 0.0 <= result["score"] <= 1.0
    print(f"  Single: {result}")

    encoded = api.encode_response(result)
    assert encoded == result


def test_batch():
    api = SentimentAPI()
    api.setup("cpu")

    texts = [
        "I love this!",
        "This is terrible.",
        "It is what it is.",
    ]
    results = api.predict(texts)
    assert len(results) == 3
    for r in results:
        assert "label" in r
        assert "score" in r
    print(f"  Batch: {results}")


def test_fallback():
    """Test rule-based fallback by mocking ImportError."""
    api = SentimentAPI()
    api.setup("cpu")

    # Force fallback mode
    api.using_transformers = False

    texts = [
        "This is good and great!",
        "This is bad and terrible!",
        "The sky is blue.",
    ]
    results = api.predict(texts)
    assert len(results) == 3
    assert results[0]["label"] == "POSITIVE"
    assert results[1]["label"] == "NEGATIVE"
    assert results[2]["label"] == "NEUTRAL"
    print(f"  Fallback: {results}")


if __name__ == "__main__":
    print("Testing single inference...")
    test_single()

    print("Testing batch inference...")
    test_batch()

    print("Testing fallback mode...")
    test_fallback()

    print("All sentiment model logic tests passed.")
