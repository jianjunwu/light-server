"""Validate the echo model logic without starting the server."""

import sys

sys.path.insert(0, "./model_repo/echo_model/1")

from model import EchoAPI


def test_echo():
    api = EchoAPI()
    api.setup("cpu")

    decoded = api.decode_request({"input": "hello"})
    assert decoded == "hello"

    output = api.predict(decoded)
    assert output == "hello"

    encoded = api.encode_response(output)
    assert encoded == {"output": "hello"}

    print("Echo model logic test passed.")


if __name__ == "__main__":
    test_echo()
