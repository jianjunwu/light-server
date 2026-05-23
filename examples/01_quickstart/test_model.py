"""Validate the hello model logic without starting the server."""

import sys

sys.path.insert(0, "./model_repo/hello_model/1")

from model import HelloAPI


def test_hello():
    api = HelloAPI()
    api.setup("cpu")

    # Test greeting
    decoded = api.decode_request({"text": "hello"})
    output = api.predict(decoded)
    assert output["original"] == "hello"
    assert output["mood"] == "greeting"
    assert "hello" in output["enhanced"].lower()

    # Test positive
    decoded = api.decode_request({"text": "I love this"})
    output = api.predict(decoded)
    assert output["mood"] == "positive"

    # Test negative
    decoded = api.decode_request({"text": "I hate rain"})
    output = api.predict(decoded)
    assert output["mood"] == "negative"

    # Test question
    decoded = api.decode_request({"text": "What is this?"})
    output = api.predict(decoded)
    assert output["mood"] == "question"

    # Test Chinese
    decoded = api.decode_request({"text": "你好"})
    output = api.predict(decoded)
    assert output["mood"] == "greeting"

    # Test neutral
    decoded = api.decode_request({"text": "xyz123"})
    output = api.predict(decoded)
    assert output["mood"] == "neutral"

    print("✅ Model logic test passed!")


if __name__ == "__main__":
    test_hello()
