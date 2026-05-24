from pathlib import Path

import pytest


@pytest.fixture
def sample_config():
    return {
        "server": {
            "http_port": 18000,
            "grpc_port": 18001,
            "metrics_port": 18002,
            "host": "127.0.0.1",
            "num_api_servers": 1,
        },
        "grpc": {"enabled": False},
        "metrics": {"enabled": False},
        "model_repository": {
            "path": "./model_repo",
            "control_mode": "explicit",
        },
        "load_models": ["test_model"],
    }


@pytest.fixture
def isolated_model_repo(tmp_path):
    """Create a temporary model repository with all test models.

    Returns the path to the created model_repo directory.
    """
    repo = tmp_path / "model_repo"

    # test_model/1/model.py
    test_model_v1 = repo / "test_model" / "1"
    test_model_v1.mkdir(parents=True)
    (test_model_v1 / "model.py").write_text(
        'import sys\n'
        'from pathlib import Path\n'
        'sys.path.insert(0, str(Path(__file__).parent))\n\n'
        'from litserve import LitAPI\n'
        'from prometheus_client import Counter, Histogram\n'
        'import utils\n\n'
        'class TestModel(LitAPI):\n'
        '    input_tokens = Counter("input_tokens_total", "Total input tokens")\n'
        '    predict_latency = Histogram("predict_latency_seconds", "Predict latency")\n\n'
        '    def setup(self, device):\n'
        '        pass\n\n'
        '    def decode_request(self, request):\n'
        '        return request\n\n'
        '    def predict(self, x):\n'
        '        with self.predict_latency.time():\n'
        '            return {"output": utils.compute(x["input"])}\n\n'
        '    def encode_response(self, output):\n'
        '        return output\n'
    )
    (test_model_v1 / "utils.py").write_text(
        'def compute(x):\n'
        '    return x ** 2\n'
    )
    (test_model_v1 / "config.yaml").write_text(
        'hot_reload: true\n'
        'hot_reload_patterns:\n'
        '  - "*.py"\n'
    )

    # test_model/2/model.py
    test_model_v2 = repo / "test_model" / "2"
    test_model_v2.mkdir(parents=True)
    (test_model_v2 / "model.py").write_text(
        'import sys\n'
        'from pathlib import Path\n'
        'sys.path.insert(0, str(Path(__file__).parent))\n\n'
        'from litserve import LitAPI\n'
        'from prometheus_client import Counter, Histogram\n'
        'import utils\n\n'
        'class TestModel(LitAPI):\n'
        '    input_tokens = Counter("input_tokens_total", "Total input tokens")\n'
        '    predict_latency = Histogram("predict_latency_seconds", "Predict latency")\n\n'
        '    def setup(self, device):\n'
        '        pass\n\n'
        '    def decode_request(self, request):\n'
        '        return request\n\n'
        '    def predict(self, x):\n'
        '        with self.predict_latency.time():\n'
        '            return {"output": utils.compute(x["input"])}\n\n'
        '    def encode_response(self, output):\n'
        '        return output\n\n'
        '    def on_file_changed(self, changed_files):\n'
        '        return "handled"\n'
    )
    (test_model_v2 / "utils.py").write_text(
        'def compute(x):\n'
        '    return x ** 3\n'
    )

    # test_model/model_config.yaml
    (repo / "test_model" / "model_config.yaml").write_text(
        'default_version: "1"\n'
        'load_policy: explicit\n'
        'versions_to_load:\n'
        '  - "1"\n'
        '  - "2"\n'
        'auto_activate_on_load: true\n'
        'max_loaded_versions: 2\n'
    )

    # stream_model/1/model.py
    stream_dir = repo / "stream_model" / "1"
    stream_dir.mkdir(parents=True)
    (stream_dir / "model.py").write_text(
        'from litserve import LitAPI\n\n'
        'class StreamModel(LitAPI):\n'
        '    def setup(self, device):\n'
        '        pass\n\n'
        '    def decode_request(self, request):\n'
        '        return request\n\n'
        '    def predict(self, x):\n'
        '        return {"echo": x}\n\n'
        '    def encode_response(self, output):\n'
        '        return output\n'
    )
    (stream_dir / "config.yaml").write_text(
        'stream: true\n'
        'bidirectional: true\n'
    )

    # my_ensemble/1/config.yaml
    ensemble_dir = repo / "my_ensemble" / "1"
    ensemble_dir.mkdir(parents=True)
    (ensemble_dir / "config.yaml").write_text(
        'ensemble:\n'
        '  steps:\n'
        '    - name: square\n'
        '      model: test_model\n'
        '      version: "1"\n'
        '      inputs:\n'
        '        input: "$request.value"\n'
        '    - name: cube\n'
        '      model: test_model\n'
        '      version: "2"\n'
        '      inputs:\n'
        '        input: "$square.output"\n'
    )

    # cb_model/1/model.py
    cb_dir = repo / "cb_model" / "1"
    cb_dir.mkdir(parents=True)
    (cb_dir / "model.py").write_text(
        'from litserve import LitAPI\n\n'
        'class CBModel(LitAPI):\n'
        '    def setup(self, device):\n'
        '        pass\n\n'
        '    def decode_request(self, request):\n'
        '        return request\n\n'
        '    def predict(self, inputs, generated_sequences):\n'
        '        return ["tok_0"] * len(inputs)\n\n'
        '    def encode_response(self, output):\n'
        '        return {"output": output}\n\n'
        '    def has_finished(self, uid, token, max_sequence_length):\n'
        '        return token == "<EOS>"\n\n'
        '    def has_active_requests(self):\n'
        '        return bool(getattr(self, "_active", {}))\n\n'
        '    def has_capacity(self):\n'
        '        active = getattr(self, "_active", {})\n'
        '        return len(active) < getattr(self, "max_batch_size", 1)\n'
    )
    (cb_dir / "config.yaml").write_text(
        'continuous_batching: true\n'
        'stream: true\n'
        'max_sequence_length: 10\n'
        'max_batch_size: 4\n'
    )

    return repo


@pytest.fixture
def model_repo(isolated_model_repo):
    return isolated_model_repo
