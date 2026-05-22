"""Manifest dataclass and validation for model artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


class ManifestValidationError(ValueError):
    """Raised when manifest validation fails."""


@dataclass
class FileEntry:
    """Checksum entry for a single file in the artifact."""

    size: int
    sha256: str


@dataclass
class VersionEntry:
    """Entry point for a model version."""

    model_py: str
    config: str


@dataclass
class Metadata:
    """Build and environment metadata."""

    framework: str = "litserve"
    python_version: str = ""
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class Signature:
    """Cryptographic signature."""

    alg: str = ""
    value: str = ""
    signer: str = ""


@dataclass
class Manifest:
    """Artifact manifest describing contents and provenance."""

    manifest_version: str = "1.0"
    name: str = ""
    version: str = ""
    build_id: str = ""
    created_at: str = ""
    entrypoint: dict[str, dict[str, VersionEntry]] = field(default_factory=dict)
    files: dict[str, FileEntry] = field(default_factory=dict)
    metadata: Metadata = field(default_factory=Metadata)
    signature: Signature = field(default_factory=Signature)

    def validate(self) -> None:
        """Validate manifest fields."""
        if not self.name:
            raise ManifestValidationError("manifest.name is required")
        if not self.version:
            raise ManifestValidationError("manifest.version is required")
        if not SEMVER_PATTERN.match(self.version):
            raise ManifestValidationError(f"manifest.version '{self.version}' is not valid semver")
        if not self.build_id:
            raise ManifestValidationError("manifest.build_id is required")
        if not self.created_at:
            raise ManifestValidationError("manifest.created_at is required")
        if not self.files:
            raise ManifestValidationError("manifest.files must not be empty")
        for path, entry in self.files.items():
            if not entry.sha256:
                raise ManifestValidationError(f"manifest.files['{path}'].sha256 is required")

    def to_dict(self) -> dict[str, Any]:
        """Convert manifest to a plain dict."""
        return asdict(self)

    def to_canonical_json(self) -> str:
        """Return canonical JSON for signing (sorted keys, no extra whitespace)."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        """Build Manifest from a plain dict."""
        files: dict[str, FileEntry] = {}
        for path, fdata in data.get("files", {}).items():
            files[path] = FileEntry(size=fdata.get("size", 0), sha256=fdata.get("sha256", ""))

        entrypoint: dict[str, dict[str, VersionEntry]] = {}
        versions_data = data.get("entrypoint", {}).get("versions", {})
        if versions_data:
            versions: dict[str, VersionEntry] = {}
            for ver_key, ver_data in versions_data.items():
                versions[ver_key] = VersionEntry(
                    model_py=ver_data.get("model_py", ""),
                    config=ver_data.get("config", ""),
                )
            entrypoint["versions"] = versions

        meta = data.get("metadata", {})
        metadata = Metadata(
            framework=meta.get("framework", "litserve"),
            python_version=meta.get("python_version", ""),
            dependencies=meta.get("dependencies", {}),
            tags=meta.get("tags", []),
        )

        sig = data.get("signature", {})
        signature = Signature(
            alg=sig.get("alg", ""),
            value=sig.get("value", ""),
            signer=sig.get("signer", ""),
        )

        return cls(
            manifest_version=data.get("manifest_version", "1.0"),
            name=data.get("name", ""),
            version=data.get("version", ""),
            build_id=data.get("build_id", ""),
            created_at=data.get("created_at", ""),
            entrypoint=entrypoint,
            files=files,
            metadata=metadata,
            signature=signature,
        )

    @classmethod
    def from_json(cls, raw: str) -> Manifest:
        """Parse manifest from JSON string."""
        return cls.from_dict(json.loads(raw))

    @classmethod
    def from_file(cls, path: Path) -> Manifest:
        """Load manifest from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
