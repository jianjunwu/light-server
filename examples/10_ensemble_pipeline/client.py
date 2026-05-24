"""Client for the ensemble pipeline demo.

Demonstrates calling an ensemble model that orchestrates:
  square(x) + double(x) = x^2 + 2x
"""

import requests

BASE = "http://127.0.0.1:8000"


def test_single():
    """Test single inference through the ensemble."""
    x = 5
    r = requests.post(
        f"{BASE}/v2/models/math_pipeline/infer",
        json={"x": x},
    )
    result = r.json()
    expected = x * x + x * 2  # 25 + 10 = 35
    print(f"  math_pipeline({x}) = {result['result']}  (expected: {expected})")
    assert result["result"] == expected, f"Expected {expected}, got {result['result']}"


def test_multiple():
    """Test multiple inputs."""
    print("\n  Multiple inputs:")
    for x in [1, 2, 3, 4, 10]:
        r = requests.post(
            f"{BASE}/v2/models/math_pipeline/infer",
            json={"x": x},
        )
        result = r.json()
        expected = x * x + x * 2
        print(f"    math_pipeline({x}) = {result['result']:3}  (expected: {expected})")
        assert result["result"] == expected


def test_individual_models():
    """Verify individual sub-models work."""
    print("\n  Individual sub-models:")

    r = requests.post(f"{BASE}/v2/models/square/infer", json={"x": 5})
    print(f"    square(5)    = {r.json()['result']}  (expected: 25)")
    assert r.json()["result"] == 25

    r = requests.post(f"{BASE}/v2/models/double/infer", json={"x": 5})
    print(f"    double(5)    = {r.json()['result']}  (expected: 10)")
    assert r.json()["result"] == 10

    r = requests.post(f"{BASE}/v2/models/combine/infer", json={"a": 25, "b": 10})
    print(f"    combine(25,10) = {r.json()['result']}  (expected: 35)")
    assert r.json()["result"] == 35


def main():
    print("=" * 50)
    print("  Ensemble Pipeline Demo")
    print("  Pipeline: square(x) + double(x) = x^2 + 2x")
    print("=" * 50)

    print("\n  Single inference:")
    test_single()

    test_multiple()
    test_individual_models()

    print("\n" + "=" * 50)
    print("  All tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    main()
