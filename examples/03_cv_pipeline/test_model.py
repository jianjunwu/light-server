"""Validate CV model logic without starting the server."""

import sys

sys.path.insert(0, "./model_repo/preprocess/1")
sys.path.insert(0, "./model_repo/predict/1")

from preprocess.model import PreprocessAPI
from predict.model import PredictAPI


def test_preprocess():
    api = PreprocessAPI()
    api.setup("cpu")

    # Test with empty request (generates test pattern)
    decoded = api.decode_request({})
    output = api.predict(decoded)
    encoded = api.encode_response(output)

    assert encoded["shape"] == [3, 224, 224]
    assert len(encoded["tensor"]) == 3
    print(f"Preprocess output shape: {encoded['shape']}")
    print("Preprocess model logic test passed.")


def test_predict():
    api = PredictAPI()
    api.setup("cpu")

    # Create a dummy tensor [3, 224, 224]
    dummy_tensor = [[[0.5] * 224 for _ in range(224)] for _ in range(3)]
    decoded = api.decode_request({"tensor": dummy_tensor})
    output = api.predict(decoded)
    encoded = api.encode_response(output)

    assert "top5" in encoded
    assert len(encoded["top5"]) <= 5
    assert "class_name" in encoded["top5"][0]
    assert "confidence" in encoded["top5"][0]
    print(f"Predict top-1: {encoded['top5'][0]['class_name']} "
          f"(confidence: {encoded['top5'][0]['confidence']})")
    print("Predict model logic test passed.")


if __name__ == "__main__":
    test_preprocess()
    test_predict()
