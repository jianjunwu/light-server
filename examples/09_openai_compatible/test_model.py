"""Validate the hello model logic without starting the server."""

import sys

sys.path.insert(0, "./model_repo/hello_model/1")

from model import HelloAPI


def test_hello():
    api = HelloAPI()
    api.setup("cpu")

    decoded = api.decode_request({"text": "hello"})
    output = api.predict(decoded)
    assert output["original"] == "hello"
    assert output["mood"] == "greeting"

    decoded = api.decode_request({"text": "I love this"})
    output = api.predict(decoded)
    assert output["mood"] == "positive"

    print("✅ Model logic test passed!")


if __name__ == "__main__":
    test_hello()
