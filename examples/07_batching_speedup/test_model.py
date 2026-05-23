"""Validate the compute model logic without starting the server."""

import sys

sys.path.insert(0, "./model_repo/compute_model/1")

from model import ComputeAPI


def test_compute():
    api = ComputeAPI()
    api.setup("cpu")

    # Single request (as if batch_size=1)
    decoded = api.decode_request({"number": 5})
    output = api.predict([decoded])
    assert output == [{"result": 25, "batch_size": 1}]

    # Batch request
    decoded = [1, 2, 3]
    output = api.predict(decoded)
    assert output == [
        {"result": 1, "batch_size": 3},
        {"result": 4, "batch_size": 3},
        {"result": 9, "batch_size": 3},
    ]

    print("✅ Model logic test passed!")


if __name__ == "__main__":
    test_compute()
