"""Dynamic module loading for model files."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

from litserve import LitAPI


def import_module_from_file(
    file_path: Path,
    module_name: str | None = None,
    suppress_prometheus: bool = False,
) -> ModuleType:
    """Import a Python module from a file path."""
    file_path = Path(file_path).resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Model file not found: {file_path}")

    if module_name is None:
        module_name = file_path.stem

    # Avoid re-importing with same name
    unique_name = f"_light_server_dynamic_{module_name}_{id(file_path)}"

    spec = importlib.util.spec_from_file_location(unique_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module

    # Allow absolute imports of sibling modules in the same directory
    parent_dir = str(file_path.parent)
    added_to_path = False
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
        added_to_path = True

    # In the main process, temporarily suppress prometheus metric registration
    # to avoid duplicate errors when reloading model files. Workers need real
    # registration (via multiproc mode), so we only patch when explicitly asked.
    _prometheus_patched = False
    try:
        if suppress_prometheus:
            import prometheus_client
            _original_register = prometheus_client.REGISTRY.register
            prometheus_client.REGISTRY.register = lambda *args, **kwargs: None
            _prometheus_patched = True
    except Exception:
        pass

    try:
        spec.loader.exec_module(module)
    finally:
        if added_to_path:
            sys.path.remove(parent_dir)
        if _prometheus_patched:
            try:
                import prometheus_client
                prometheus_client.REGISTRY.register = _original_register
            except Exception:
                pass

    return module


def find_litapi_class(module: ModuleType) -> type[LitAPI]:
    """Find the first LitAPI subclass in a module."""
    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        if (
            isinstance(obj, type)
            and issubclass(obj, LitAPI)
            and obj is not LitAPI
            and obj.__name__ != "LitAPI"
        ):
            return obj
    raise ValueError(f"No LitAPI subclass found in module {module.__name__}")


def load_litapi_from_module(module_path: str, class_name: str | None = None) -> type[LitAPI]:
    """Load a LitAPI class from 'module.path:ClassName' syntax."""
    if ":" in module_path:
        module_path, class_name = module_path.split(":", 1)

    module = importlib.import_module(module_path)

    if class_name:
        cls = getattr(module, class_name, None)
        if cls is None:
            raise ValueError(f"Class {class_name} not found in module {module_path}")
        if not issubclass(cls, LitAPI):
            raise ValueError(f"{class_name} is not a LitAPI subclass")
        return cls

    return find_litapi_class(module)


def load_litapi_from_file(
    file_path: Path, suppress_prometheus: bool = False
) -> type[LitAPI]:
    """Load a LitAPI class from a model.py file."""
    module = import_module_from_file(
        file_path, suppress_prometheus=suppress_prometheus
    )
    return find_litapi_class(module)
