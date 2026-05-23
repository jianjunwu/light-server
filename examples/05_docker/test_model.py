"""Validate the sentiment model logic without starting the server."""

import sys

sys.path.insert(0, "./model_repo/demo_model/1")

from model import SentimentAPI


def test_sentiment():
    api = SentimentAPI()
    api.setup("cpu")

    # Positive
    decoded = api.decode_request({"text": "This is a great and amazing product"})
    output = api.predict(decoded)
    encoded = api.encode_response(output)
    assert encoded["sentiment"] == "positive"
    assert encoded["positive_words"] >= 2
    print(f"Positive: {encoded}")

    # Negative
    decoded = api.decode_request({"text": "This is bad and terrible"})
    output = api.predict(decoded)
    encoded = api.encode_response(output)
    assert encoded["sentiment"] == "negative"
    assert encoded["negative_words"] >= 2
    print(f"Negative: {encoded}")

    # Neutral
    decoded = api.decode_request({"text": "The weather is okay today"})
    output = api.predict(decoded)
    encoded = api.encode_response(output)
    assert encoded["sentiment"] == "neutral"
    print(f"Neutral: {encoded}")

    print("Sentiment model logic test passed.")


if __name__ == "__main__":
    test_sentiment()
