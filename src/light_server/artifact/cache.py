"""Artifact cache for extracting .lma files on demand."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from light_server.artifact.manifest import Manifest
from light_server.artifact.unpacker import ModelUnpacker


class ArtifactCache:
    """Cache extracted artifacts by build_id to avoid repeated unpacking."""

    def __init__(self, cache_root: Path | None = None):
        """Initialize cache.

        Args:
            cache_root: Directory to store extracted artifacts.
                Defaults to ~/.cache/light_server/artifacts/
        """
        if cache_root is None:
            cache_root = Path.home() / ".cache" / "light_server" / "artifacts"
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, manifest: Manifest) -> str:
        """Generate a unique cache directory name from manifest."""
        raw = f"{manifest.name}-{manifest.version}-{manifest.build_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def get_or_extract(self, artifact_path: Path) -> Path:
        """Return the path to the extracted model directory.

        If already cached, returns the cached directory.
        Otherwise validates and extracts the artifact first.

        Returns:
            Path to the extracted model directory.
        """
        artifact_path = Path(artifact_path)
        unpacker = ModelUnpacker(artifact_path)
        manifest = unpacker.validate()

        cache_key = self._cache_key(manifest)
        cached_dir = self.cache_root / cache_key / manifest.name

        if cached_dir.exists():
            return cached_dir

        extract_base = self.cache_root / cache_key
        extract_base.mkdir(parents=True, exist_ok=True)
        unpacked = unpacker.unpack(extract_base)

        return unpacked

    def purge(self, name: str | None = None) -> int:
        """Remove cached artifacts.

        Args:
            name: If provided, only purge artifacts for this model name.
                Otherwise purges all cached artifacts.

        Returns:
            Number of directories removed.
        """
        removed = 0
        for entry in self.cache_root.iterdir():
            if not entry.is_dir():
                continue
            if name is not None:
                # Check if this cache entry contains the named model
                model_dir = entry / name
                if not model_dir.exists():
                    continue
            shutil.rmtree(entry)
            removed += 1
        return removed
