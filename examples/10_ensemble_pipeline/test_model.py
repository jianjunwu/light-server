"""Test model logic without starting the server."""

import importlib.util
import sys
from pathlib import Path


def _load_module(name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BASE = Path(__file__).parent / "model_repo"

square_mod = _load_module("square_model", BASE / "square" / "1" / "model.py")
double_mod = _load_module("double_model", BASE / "double" / "1" / "model.py")
combine_mod = _load_module("combine_model", BASE / "combine" / "1" / "model.py")

SquareAPI = square_mod.SquareAPI
DoubleAPI = double_mod.DoubleAPI
CombineAPI = combine_mod.CombineAPI


def test_square():
    api = SquareAPI()
    api.setup("cpu")
    assert api.predict(api.decode_request({"x": 5})) == 25
    assert api.predict(api.decode_request({"x": 3})) == 9
    print("  square: OK")


def test_double():
    api = DoubleAPI()
    api.setup("cpu")
    assert api.predict(api.decode_request({"x": 5})) == 10
    assert api.predict(api.decode_request({"x": 3})) == 6
    print("  double: OK")


def test_combine():
    api = CombineAPI()
    api.setup("cpu")
    assert api.predict(api.decode_request({"a": 25, "b": 10})) == 35
    assert api.predict(api.decode_request({"a": 9, "b": 6})) == 15
    print("  combine: OK")


def test_pipeline():
    """Simulate the ensemble pipeline end-to-end."""
    square_api = SquareAPI()
    square_api.setup("cpu")
    double_api = DoubleAPI()
    double_api.setup("cpu")
    combine_api = CombineAPI()
    combine_api.setup("cpu")

    x = 5
    square_result = square_api.encode_response(
        square_api.predict(square_api.decode_request({"x": x}))
    )
    double_result = double_api.encode_response(
        double_api.predict(double_api.decode_request({"x": x}))
    )
    final = combine_api.encode_response(
        combine_api.predict(combine_api.decode_request({
            "a": square_result["result"],
            "b": double_result["result"],
        }))
    )

    expected = x * x + x * 2
    assert final["result"] == expected, f"Expected {expected}, got {final['result']}"
    print(f"  pipeline({x}) = {final['result']} (expected {expected}): OK")


def main():
    print("Testing model logic...")
    test_square()
    test_double()
    test_combine()
    test_pipeline()
    print("All tests passed!")


if __name__ == "__main__":
    main()
