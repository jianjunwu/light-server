"""Tests for dynamic module loading utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from light_server.core.loader import (
    find_litapi_class,
    import_module_from_file,
    load_litapi_from_file,
    load_litapi_from_module,
    load_module_from_file,
)


# ------------------------------------------------------------------
# import_module_from_file
# ------------------------------------------------------------------


def test_import_module_from_file_success(tmp_path: Path):
    module_file = tmp_path / "my_module.py"
    module_file.write_text("answer = 42\n")

    module = import_module_from_file(module_file)
    assert module.answer == 42


def test_import_module_from_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        import_module_from_file(tmp_path / "nonexistent.py")


def test_import_module_from_file_allows_sibling_imports(tmp_path: Path):
    """Modules in the same directory should be importable via absolute imports."""
    sibling = tmp_path / "sibling.py"
    sibling.write_text("helper_value = 99\n")
    main = tmp_path / "main.py"
    main.write_text("import sibling\nresult = sibling.helper_value\n")

    module = import_module_from_file(main)
    assert module.result == 99


def test_import_module_from_file_suppress_prometheus(tmp_path: Path):
    """suppress_prometheus=True should prevent prometheus metric registration."""
    # Create a module that registers a prometheus metric
    module_file = tmp_path / "prom_module.py"
    module_file.write_text(
        "from prometheus_client import Counter\n"
        "my_metric = Counter('test_metric_total', 'A test metric')\n"
    )

    # With suppression: should not raise even if called twice
    mod1 = import_module_from_file(module_file, suppress_prometheus=True)
    mod2 = import_module_from_file(module_file, suppress_prometheus=True)
    assert mod1 is not mod2  # different unique module names


def test_import_module_from_file_without_suppress_prometheus(tmp_path: Path):
    """Without suppression, duplicate metric registration may occur."""
    module_file = tmp_path / "prom_module2.py"
    module_file.write_text(
        "from prometheus_client import Counter\n"
        "my_metric2 = Counter('test_metric2_total', 'A test metric')\n"
    )

    # First import should succeed
    mod1 = import_module_from_file(module_file, suppress_prometheus=False)
    assert mod1 is not None

    # Clean up: unregister the metric to avoid affecting other tests
    import prometheus_client

    for collector in list(prometheus_client.REGISTRY._collector_to_names.keys()):
        try:
            prometheus_client.REGISTRY.unregister(collector)
        except Exception:
            pass


# ------------------------------------------------------------------
# find_litapi_class
# ------------------------------------------------------------------


def test_find_litapi_class_found(tmp_path: Path):
    from litserve import LitAPI

    module_file = tmp_path / "api_module.py"
    module_file.write_text(
        "from litserve import LitAPI\n"
        "class MyAPI(LitAPI):\n"
        "    def setup(self, device): pass\n"
        "    def decode_request(self, request): return request\n"
        "    def predict(self, x): return x\n"
        "    def encode_response(self, output): return output\n"
    )
    module = import_module_from_file(module_file)
    cls = find_litapi_class(module)
    assert cls.__name__ == "MyAPI"
    assert issubclass(cls, LitAPI)


def test_find_litapi_class_excludes_base():
    """find_litapi_class should not return LitAPI itself."""
    import litserve

    with pytest.raises(ValueError, match="No LitAPI subclass"):
        find_litapi_class(litserve)


def test_find_litapi_class_not_found(tmp_path: Path):
    module_file = tmp_path / "plain.py"
    module_file.write_text("x = 1\n")
    module = import_module_from_file(module_file)
    with pytest.raises(ValueError, match="No LitAPI subclass"):
        find_litapi_class(module)


def test_find_litapi_class_multiple_subclasses_returns_first(tmp_path: Path):
    """When multiple subclasses exist, return the first one found via dir()."""
    module_file = tmp_path / "multi_api.py"
    module_file.write_text(
        "from litserve import LitAPI\n"
        "class FirstAPI(LitAPI):\n"
        "    def setup(self, device): pass\n"
        "    def decode_request(self, request): return request\n"
        "    def predict(self, x): return x\n"
        "    def encode_response(self, output): return output\n"
        "class SecondAPI(LitAPI):\n"
        "    def setup(self, device): pass\n"
        "    def decode_request(self, request): return request\n"
        "    def predict(self, x): return x\n"
        "    def encode_response(self, output): return output\n"
    )
    module = import_module_from_file(module_file)
    cls = find_litapi_class(module)
    assert cls.__name__ in ("FirstAPI", "SecondAPI")


# ------------------------------------------------------------------
# load_litapi_from_file
# ------------------------------------------------------------------


def test_load_litapi_from_file_success(tmp_path: Path):
    from litserve import LitAPI

    module_file = tmp_path / "api.py"
    module_file.write_text(
        "from litserve import LitAPI\n"
        "class TestAPI(LitAPI):\n"
        "    def setup(self, device): pass\n"
        "    def decode_request(self, request): return request\n"
        "    def predict(self, x): return x\n"
        "    def encode_response(self, output): return output\n"
    )
    cls = load_litapi_from_file(module_file)
    assert cls.__name__ == "TestAPI"
    assert issubclass(cls, LitAPI)


def test_load_litapi_from_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_litapi_from_file(tmp_path / "missing.py")


# ------------------------------------------------------------------
# load_litapi_from_module
# ------------------------------------------------------------------


def test_load_litapi_from_module_with_colon_syntax():
    """module:Class syntax should load a specific class."""
    cls = load_litapi_from_module("litserve.api:LitAPI")
    import litserve

    assert cls is litserve.LitAPI


def test_load_litapi_from_module_without_class(tmp_path: Path):
    """Without colon, should use find_litapi_class on the module."""
    module_file = tmp_path / "my_api_module.py"
    module_file.write_text(
        "from litserve import LitAPI\n"
        "class FoundAPI(LitAPI):\n"
        "    def setup(self, device): pass\n"
        "    def decode_request(self, request): return request\n"
        "    def predict(self, x): return x\n"
        "    def encode_response(self, output): return output\n"
    )
    # Add temp path to sys.path so importlib can find it
    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        cls = load_litapi_from_module("my_api_module")
        assert cls.__name__ == "FoundAPI"
    finally:
        sys.path.remove(str(tmp_path))


def test_load_litapi_from_module_class_not_found():
    with pytest.raises(ValueError, match="Class MissingClass not found"):
        load_litapi_from_module("litserve.api:MissingClass")


def test_load_litapi_from_module_not_litapi():
    with pytest.raises(ValueError, match="is not a LitAPI subclass"):
        load_litapi_from_module("litserve.server:LitServer")


# ------------------------------------------------------------------
# load_module_from_file
# ------------------------------------------------------------------


def test_load_module_from_file_success(tmp_path: Path):
    module_file = tmp_path / "plain_module.py"
    module_file.write_text("value = 123\n")
    module = load_module_from_file(module_file)
    assert module.value == 123


def test_load_module_from_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_module_from_file(tmp_path / "missing.py")


# ------------------------------------------------------------------
# Integration: isolated_model_repo fixture
# ------------------------------------------------------------------


def test_load_from_isolated_repo(isolated_model_repo: Path):
    """Load a real LitAPI from the fixture model repository."""
    model_py = isolated_model_repo / "test_model" / "1" / "model.py"
    cls = load_litapi_from_file(model_py, suppress_prometheus=True)
    assert cls.__name__ == "TestModel"


def test_load_litapi_with_suppress_prometheus_twice(isolated_model_repo: Path):
    """suppress_prometheus=True allows loading the same file multiple times."""
    model_py = isolated_model_repo / "test_model" / "1" / "model.py"
    cls1 = load_litapi_from_file(model_py, suppress_prometheus=True)
    cls2 = load_litapi_from_file(model_py, suppress_prometheus=True)
    assert cls1.__name__ == "TestModel"
    assert cls2.__name__ == "TestModel"
