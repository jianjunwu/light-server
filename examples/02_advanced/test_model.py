"""Validate advanced model logic without starting the server."""

import sys

sys.path.insert(0, "./model_repo/advanced_model/1")

from model import AdvancedAPI as V1API


def test_v1():
    api = V1API()
    api.setup("cpu")
    api.config = {"multiplier": 3}
    api.setup("cpu")  # re-setup with config

    decoded = api.decode_request({"input": 5})
    assert decoded == 5

    output = api.predict(decoded)
    assert output == 15  # 5 * 3

    encoded = api.encode_response(output)
    assert encoded == {"result": 15}

    # Test batching
    output = api.predict([1, 2, 3])
    assert output == [3, 6, 9]

    print("Advanced v1 model logic test passed.")


def test_v2():
    sys.path.insert(0, "./model_repo/advanced_model/2")
    from model import AdvancedAPI as V2API

    api = V2API()
    api.config = {"addend": 50}
    api.setup("cpu")

    decoded = api.decode_request({"input": 5})
    output = api.predict(decoded)
    assert output == 55  # 5 + 50

    encoded = api.encode_response(output)
    assert encoded == {"result": 55}

    print("Advanced v2 model logic test passed.")


if __name__ == "__main__":
    test_v1()
    test_v2()
