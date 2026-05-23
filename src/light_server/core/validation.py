"""Input validation helpers for model names and versions."""

from __future__ import annotations

import re


# Allow alphanumeric, underscore, hyphen, dot for versions (e.g. "1.0.2")
_VERSION_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
# Model names should not contain dots (they are directory names)
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

MAX_NAME_LEN = 64
MAX_VERSION_LEN = 32


def validate_model_name(name: str) -> None:
    """Validate a model name. Raises ValueError if invalid."""
    if not name:
        raise ValueError("model name must not be empty")
    if len(name) > MAX_NAME_LEN:
        raise ValueError(f"model name too long (max {MAX_NAME_LEN})")
    if not _NAME_RE.match(name):
        raise ValueError(
            "model name contains invalid characters; allowed: a-zA-Z0-9_-"
        )


def validate_version(version: str) -> None:
    """Validate a model version. Raises ValueError if invalid."""
    if not version:
        raise ValueError("version must not be empty")
    if len(version) > MAX_VERSION_LEN:
        raise ValueError(f"version too long (max {MAX_VERSION_LEN})")
    if not _VERSION_RE.match(version):
        raise ValueError(
            "version contains invalid characters; allowed: a-zA-Z0-9_.-"
        )
