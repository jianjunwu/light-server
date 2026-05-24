"""Model artifact unpacker: validate and extract .lma files."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

from light_server.artifact.manifest import Manifest


class ArtifactCorruptedError(ValueError):
    """Raised when artifact integrity check fails."""


class ArtifactNotFoundError(FileNotFoundError):
    """Raised when artifact file is missing."""


class SignatureInvalidError(ValueError):
    """Raised when signature verification fails."""


class ModelUnpacker:
    """Validate and extract .lma artifacts."""

    def __init__(self, artifact_path: Path):
        self.artifact_path = Path(artifact_path)
        self.manifest: Manifest | None = None

    def validate(self, public_key_pem: bytes | None = None) -> Manifest:
        """Validate artifact integrity and optionally verify signature.

        Returns:
            The validated manifest.

        Raises:
            ArtifactNotFoundError: artifact file does not exist.
            ArtifactCorruptedError: zip is corrupt or checksums mismatch.
            SignatureInvalidError: signature verification fails.
        """
        if not self.artifact_path.exists():
            raise ArtifactNotFoundError(f"Artifact not found: {self.artifact_path}")

        try:
            with zipfile.ZipFile(self.artifact_path, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    raise ArtifactCorruptedError("manifest.json missing from artifact")

                manifest_raw = zf.read("manifest.json").decode("utf-8")
                manifest = Manifest.from_json(manifest_raw)
                manifest.validate()

                # Verify file checksums
                for rel_path, entry in manifest.files.items():
                    if rel_path not in zf.namelist():
                        raise ArtifactCorruptedError(f"File missing from artifact: {rel_path}")
                    data = zf.read(rel_path)
                    actual_sha256 = hashlib.sha256(data).hexdigest()
                    if actual_sha256 != entry.sha256:
                        raise ArtifactCorruptedError(
                            f"Checksum mismatch for {rel_path}: "
                            f"expected {entry.sha256}, got {actual_sha256}"
                        )

                self.manifest = manifest
        except zipfile.BadZipFile as e:
            raise ArtifactCorruptedError(f"Invalid artifact zip: {e}") from e

        # Verify signature if key provided
        if public_key_pem is not None:
            from light_server.artifact.crypto import verify_manifest

            if not verify_manifest(self.manifest, public_key_pem):
                raise SignatureInvalidError("Artifact signature verification failed")

        return self.manifest

    def unpack(self, target_dir: Path) -> Path:
        """Extract artifact to target directory after validation.

        Returns:
            Path to the extracted model directory (target_dir/{name}).

        Raises:
            RuntimeError: if validate() was not called first.
        """
        if self.manifest is None:
            raise RuntimeError("validate() must be called before unpack()")

        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        model_dir = target_dir / self.manifest.name
        if model_dir.exists():
            import shutil

            shutil.rmtree(model_dir)

        with zipfile.ZipFile(self.artifact_path, "r") as zf:
            for rel_path in self.manifest.files:
                data = zf.read(rel_path)

                # Security: reject path traversal in artifact entries
                path_parts = Path(rel_path).parts
                if ".." in path_parts or Path(rel_path).is_absolute():
                    raise ArtifactCorruptedError(f"Invalid path in artifact: {rel_path}")

                dest = model_dir / rel_path
                # Defense-in-depth: ensure resolved path stays inside model_dir
                try:
                    dest.resolve().relative_to(model_dir.resolve())
                except ValueError:
                    raise ArtifactCorruptedError(f"Path traversal detected: {rel_path}")

                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(data)

        return model_dir
