"""Validate the LLM model logic without starting the server."""

import sys
sys.path.insert(0, "./model_repo/llm_model/1")

from model import LLMAPI


def test_mock_generation():
    api = LLMAPI()
    api.setup("cpu")

    request = {"prompt": "Hello world", "max_tokens": 5, "temperature": 0.7}
    decoded = api.decode_request(request)
    assert decoded["prompt"] == "Hello world"
    assert decoded["max_tokens"] == 5

    tokens = list(api.predict(decoded))
    assert len(tokens) == 6  # prompt_echo + 5 generated tokens
    assert tokens[0]["type"] == "prompt_echo"
    assert "token" in tokens[1]
    print(f"Generated {len(tokens)} tokens: {[t.get('token', '') for t in tokens]}")

    # Verify encode_response passes through
    encoded = api.encode_response(tokens[1])
    assert encoded == tokens[1]

    print("LLM model logic test passed.")


if __name__ == "__main__":
    test_mock_generation()
