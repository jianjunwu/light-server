"""Model artifact packer: create .lma files from model directories."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from light_server.artifact.manifest import FileEntry, Manifest, Metadata, VersionEntry


# Files/directories to ignore when packing
DEFAULT_IGNORE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".git",
    ".gitignore",
    ".DS_Store",
    "*.lma",
]


def _should_ignore(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any ignore pattern."""
    parts = Path(rel_path).parts
    for pat in patterns:
        # Match against any path component or the full relative path
        if any(fnmatch.fnmatch(part, pat) for part in parts):
            return True
        if fnmatch.fnmatch(rel_path, pat):
            return True
    return False


def _compute_sha256(filepath: Path) -> str:
    """Compute SHA256 hex digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_git_sha(cwd: Path | None = None) -> str | None:
    """Get short git SHA, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _generate_build_id(cwd: Path | None = None) -> str:
    """Generate build_id: {YYYYMMDD}-{git_sha_or_random}."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    git_sha = _get_git_sha(cwd)
    if git_sha:
        return f"{today}-{git_sha}"
    import random
    import string

    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=7))
    return f"{today}-{rand}"


class ModelPacker:
    """Pack a model directory into a .lma artifact."""

    def __init__(
        self,
        model_dir: Path,
        version: str,
        build_id: str | None = None,
        ignore_patterns: list[str] | None = None,
    ):
        """Initialize packer.

        Args:
            model_dir: Path to model_repo/{model_name}/ directory.
            version: Semver version string (e.g. "1.2.0").
            build_id: Optional build identifier. Auto-generated if not provided.
            ignore_patterns: Additional glob patterns to ignore when packing.
        """
        self.model_dir = Path(model_dir)
        self.version = version
        self.build_id = build_id or _generate_build_id(self.model_dir)
        self.ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)
        if ignore_patterns:
            self.ignore_patterns.extend(ignore_patterns)
        self.manifest: Manifest | None = None
        self._artifact_path: Path | None = None
        self._file_paths: list[tuple[str, Path]] = []

    def pack(self, output_dir: Path) -> Path:
        """Create the .lma artifact.

        Returns:
            Path to the created artifact file.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        model_name = self.model_dir.name
        artifact_name = f"{model_name}-{self.version}-{self.build_id}.lma"
        artifact_path = output_dir / artifact_name

        # Gather files and compute checksums
        files: dict[str, FileEntry] = {}
        file_paths: list[tuple[str, Path]] = []

        for root, _dirs, filenames in os.walk(self.model_dir):
            for filename in filenames:
                abs_path = Path(root) / filename
                rel_path = abs_path.relative_to(self.model_dir).as_posix()
                if _should_ignore(rel_path, self.ignore_patterns):
                    continue
                sha256 = _compute_sha256(abs_path)
                size = abs_path.stat().st_size
                files[rel_path] = FileEntry(size=size, sha256=sha256)
                file_paths.append((rel_path, abs_path))

        # Build entrypoint map from version subdirectories
        entrypoint_versions: dict[str, VersionEntry] = {}
        for item in self.model_dir.iterdir():
            if item.is_dir():
                ver = item.name
                model_py = f"{ver}/model.py"
                config_yaml = f"{ver}/config.yaml"
                entrypoint_versions[ver] = VersionEntry(
                    model_py=model_py,
                    config=config_yaml,
                )

        # Collect metadata
        metadata = Metadata(
            framework="litserve",
            python_version="",
            dependencies=self._read_dependencies(),
            tags=[],
        )

        self.manifest = Manifest(
            name=model_name,
            version=self.version,
            build_id=self.build_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            entrypoint={"versions": entrypoint_versions},
            files=files,
            metadata=metadata,
        )

        self._artifact_path = artifact_path
        self._file_paths = file_paths

        # Write artifact
        with zipfile.ZipFile(artifact_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Write manifest first
            zf.writestr("manifest.json", self.manifest.to_canonical_json())
            # Write files
            for rel_path, abs_path in file_paths:
                zf.write(abs_path, rel_path)

        return artifact_path

    def sign(self, private_key_pem: bytes, signer: str = "") -> None:
        """Sign the manifest and rewrite the artifact. Must be called after pack()."""
        if self.manifest is None:
            raise RuntimeError("pack() must be called before sign()")
        if self._artifact_path is None:
            raise RuntimeError("pack() must be called before sign()")
        from light_server.artifact.crypto import sign_manifest

        sign_manifest(self.manifest, private_key_pem, signer=signer)

        # Rewrite the entire zip with the signed manifest
        with zipfile.ZipFile(self._artifact_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", self.manifest.to_canonical_json())
            for rel_path, abs_path in self._file_paths:
                zf.write(abs_path, rel_path)

    def _read_dependencies(self) -> dict[str, list[str]]:
        """Read requirements.txt if present."""
        deps: dict[str, list[str]] = {}
        req_file = self.model_dir / "requirements.txt"
        if req_file.exists():
            with open(req_file, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            if lines:
                deps["pip"] = lines
        return deps
