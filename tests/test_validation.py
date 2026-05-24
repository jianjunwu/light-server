"""Tests for input validation helpers."""

from __future__ import annotations

import pytest

from light_server.core.exceptions import ValidationError
from light_server.core.validation import validate_model_name, validate_version


# ------------------------------------------------------------------
# validate_model_name
# ------------------------------------------------------------------


def test_validate_model_name_ok():
    """Valid names should not raise."""
    validate_model_name("model_1")
    validate_model_name("my-model")
    validate_model_name("Abc123")
    validate_model_name("x")


def test_validate_model_name_empty():
    with pytest.raises(ValidationError, match="empty"):
        validate_model_name("")


def test_validate_model_name_too_long():
    with pytest.raises(ValidationError, match="too long"):
        validate_model_name("a" * 65)


def test_validate_model_name_exact_max_len():
    """Name at exactly MAX_NAME_LEN (64) should be accepted."""
    validate_model_name("a" * 64)


def test_validate_model_name_invalid_chars():
    invalid_names = [
        "model.name",
        "model/name",
        "model:name",
        "model name",
        "model@name",
        "model$name",
        "",
    ]
    for name in invalid_names:
        with pytest.raises(ValidationError):
            validate_model_name(name)


def test_validate_model_name_dot_rejected():
    """Dots are allowed in versions but NOT in model names."""
    with pytest.raises(ValidationError):
        validate_model_name("v1.0")


# ------------------------------------------------------------------
# validate_version
# ------------------------------------------------------------------


def test_validate_version_ok():
    validate_version("1")
    validate_version("1.0.0")
    validate_version("v1-beta_2")
    validate_version("2024_05_24")


def test_validate_version_empty():
    with pytest.raises(ValidationError, match="empty"):
        validate_version("")


def test_validate_version_too_long():
    with pytest.raises(ValidationError, match="too long"):
        validate_version("a" * 33)


def test_validate_version_exact_max_len():
    """Version at exactly MAX_VERSION_LEN (32) should be accepted."""
    validate_version("a" * 32)


def test_validate_version_invalid_chars():
    invalid_versions = [
        "version/name",
        "version name",
        "version@name",
        "version$name",
        "",
    ]
    for version in invalid_versions:
        with pytest.raises(ValidationError):
            validate_version(version)


def test_validate_version_allows_dot():
    """Dots are explicitly allowed in version strings."""
    validate_version("1.0.0")
