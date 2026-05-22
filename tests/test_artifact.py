"""Tests for model artifact packing, unpacking, signing, and caching."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from light_server.artifact.cache import ArtifactCache
from light_server.artifact.crypto import generate_keypair, sign_manifest, verify_manifest
from light_server.artifact.manifest import (
    FileEntry,
    Manifest,
    ManifestValidationError,
    Metadata,
    VersionEntry,
)
from light_server.artifact.packer import ModelPacker
from light_server.artifact.unpacker import (
    ArtifactCorruptedError,
    ArtifactNotFoundError,
    ModelUnpacker,
    SignatureInvalidError,
)


@pytest.fixture
def sample_model_dir(tmp_path: Path) -> Path:
    """Create a sample model directory structure."""
    model_dir = tmp_path / "test_model"
    v1_dir = model_dir / "1"
    v1_dir.mkdir(parents=True)
    (v1_dir / "model.py").write_text("class MyAPI:\n    pass\n")
    (v1_dir / "config.yaml").write_text("max_batch_size: 4\n")
    (v1_dir / "utils.py").write_text("def helper(): pass\n")
    # Add a requirements.txt
    (model_dir / "requirements.txt").write_text("torch>=2.0\n")
    # Add files that should be ignored
    pycache = v1_dir / "__pycache__"
    pycache.mkdir()
    (pycache / "model.cpython-310.pyc").write_text("binary")
    return model_dir


# ---------------------------------------------------------------------------
# Manifest tests
# ---------------------------------------------------------------------------

def test_manifest_validation_ok():
    m = Manifest(
        name="test_model",
        version="1.2.0",
        build_id="20250522-abc1234",
        created_at="2026-05-22T09:30:00Z",
        files={"1/model.py": FileEntry(size=10, sha256="a" * 64)},
    )
    m.validate()


def test_manifest_validation_missing_name():
    m = Manifest(version="1.0.0", build_id="x", created_at="t", files={"a": FileEntry(1, "x" * 64)})
    with pytest.raises(ManifestValidationError, match="name"):
        m.validate()


def test_manifest_validation_invalid_semver():
    m = Manifest(name="x", version="not-a-version", build_id="x", created_at="t", files={"a": FileEntry(1, "x" * 64)})
    with pytest.raises(ManifestValidationError, match="semver"):
        m.validate()


def test_manifest_to_from_dict():
    m = Manifest(
        name="m",
        version="1.0.0",
        build_id="b",
        created_at="t",
        entrypoint={"versions": {"1": VersionEntry("1/model.py", "1/config.yaml")}},
        files={"1/model.py": FileEntry(size=5, sha256="a" * 64)},
        metadata=Metadata(framework="litserve", tags=["cv"]),
    )
    d = m.to_dict()
    m2 = Manifest.from_dict(d)
    assert m2.name == "m"
    assert m2.version == "1.0.0"
    assert m2.files["1/model.py"].size == 5
    assert m2.metadata.tags == ["cv"]


def test_manifest_canonical_json_deterministic():
    m = Manifest(name="m", version="1.0.0", build_id="b", created_at="t", files={"a": FileEntry(1, "x" * 64)})
    j1 = m.to_canonical_json()
    j2 = m.to_canonical_json()
    assert j1 == j2
    data = json.loads(j1)
    assert list(data.keys()) == sorted(data.keys())


# ---------------------------------------------------------------------------
# Packer tests
# ---------------------------------------------------------------------------

def test_packer_creates_artifact(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0")
    artifact_path = packer.pack(tmp_path / "out")

    assert artifact_path.exists()
    assert artifact_path.suffix == ".lma"
    assert packer.manifest is not None
    assert packer.manifest.name == "test_model"
    assert packer.manifest.version == "1.0.0"
    assert "1/model.py" in packer.manifest.files
    assert "1/config.yaml" in packer.manifest.files


def test_packer_ignores_pycache(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0")
    artifact_path = packer.pack(tmp_path / "out")

    with zipfile.ZipFile(artifact_path, "r") as zf:
        names = zf.namelist()
    assert "manifest.json" in names
    assert any("__pycache__" in n for n in names) is False


def test_packer_reads_requirements(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0")
    packer.pack(tmp_path / "out")
    assert packer.manifest is not None
    assert packer.manifest.metadata.dependencies.get("pip") == ["torch>=2.0"]


def test_packer_build_id_auto(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0")
    assert packer.build_id  # auto-generated
    assert len(packer.build_id.split("-")) == 2


def test_packer_custom_build_id(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0", build_id="custom-123")
    assert packer.build_id == "custom-123"


# ---------------------------------------------------------------------------
# Unpacker tests
# ---------------------------------------------------------------------------

def test_unpacker_validates_and_extracts(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0")
    artifact_path = packer.pack(tmp_path / "out")

    unpacker = ModelUnpacker(artifact_path)
    manifest = unpacker.validate()
    assert manifest.name == "test_model"

    extracted = unpacker.unpack(tmp_path / "extracted")
    assert (extracted / "1" / "model.py").exists()
    assert (extracted / "1" / "config.yaml").read_text() == "max_batch_size: 4\n"


def test_unpacker_missing_artifact(tmp_path: Path):
    unpacker = ModelUnpacker(tmp_path / "nonexistent.lma")
    with pytest.raises(ArtifactNotFoundError):
        unpacker.validate()


def test_unpacker_checksum_mismatch(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0")
    artifact_path = packer.pack(tmp_path / "out")

    # Corrupt the artifact by modifying a file inside the zip
    with zipfile.ZipFile(artifact_path, "a") as zf:
        zf.writestr("1/model.py", "tampered content")

    unpacker = ModelUnpacker(artifact_path)
    with pytest.raises(ArtifactCorruptedError, match="Checksum mismatch"):
        unpacker.validate()


# ---------------------------------------------------------------------------
# Crypto / signing tests
# ---------------------------------------------------------------------------

def test_generate_keypair():
    priv, pub = generate_keypair()
    assert b"PRIVATE KEY" in priv
    assert b"PUBLIC KEY" in pub


def test_sign_and_verify_manifest():
    m = Manifest(
        name="m",
        version="1.0.0",
        build_id="b",
        created_at="t",
        files={"a": FileEntry(1, "x" * 64)},
    )
    priv, pub = generate_keypair()
    sign_manifest(m, priv, signer="tester")
    assert m.signature.alg == "ed25519"
    assert m.signature.value
    assert m.signature.signer == "tester"
    assert verify_manifest(m, pub) is True


def test_verify_with_wrong_key():
    m = Manifest(
        name="m",
        version="1.0.0",
        build_id="b",
        created_at="t",
        files={"a": FileEntry(1, "x" * 64)},
    )
    priv1, _pub1 = generate_keypair()
    _priv2, pub2 = generate_keypair()
    sign_manifest(m, priv1)
    assert verify_manifest(m, pub2) is False


def test_unpacker_verifies_signature(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0")
    artifact_path = packer.pack(tmp_path / "out")

    priv, pub = generate_keypair()
    packer.sign(priv, signer="ci")

    unpacker = ModelUnpacker(artifact_path)
    manifest = unpacker.validate(public_key_pem=pub)
    assert manifest.name == "test_model"

    # Tamper with signed manifest: keep same files but change name
    bad_manifest = Manifest(
        name="tampered",
        version="9.9.9",
        build_id="bad",
        created_at="t",
        entrypoint={"versions": {"1": VersionEntry("1/model.py", "1/config.yaml")}},
        files=packer.manifest.files,
    )
    bad_manifest.signature = packer.manifest.signature  # steal signature
    with zipfile.ZipFile(artifact_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", bad_manifest.to_canonical_json())
        zf.writestr("1/model.py", (sample_model_dir / "1" / "model.py").read_bytes())
        zf.writestr("1/config.yaml", (sample_model_dir / "1" / "config.yaml").read_bytes())
        zf.writestr("1/utils.py", (sample_model_dir / "1" / "utils.py").read_bytes())
        zf.writestr("requirements.txt", (sample_model_dir / "requirements.txt").read_bytes())

    unpacker2 = ModelUnpacker(artifact_path)
    with pytest.raises(SignatureInvalidError):
        unpacker2.validate(public_key_pem=pub)


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------

def test_cache_get_or_extract(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0")
    artifact_path = packer.pack(tmp_path / "out")

    cache = ArtifactCache(cache_root=tmp_path / "cache")
    model_dir1 = cache.get_or_extract(artifact_path)
    model_dir2 = cache.get_or_extract(artifact_path)

    assert model_dir1 == model_dir2  # cached
    assert (model_dir1 / "1" / "model.py").exists()


def test_cache_purge_by_name(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0")
    artifact_path = packer.pack(tmp_path / "out")

    cache = ArtifactCache(cache_root=tmp_path / "cache")
    cache.get_or_extract(artifact_path)
    removed = cache.purge(name="test_model")
    assert removed == 1


def test_cache_purge_all(sample_model_dir: Path, tmp_path: Path):
    packer = ModelPacker(model_dir=sample_model_dir, version="1.0.0")
    artifact_path = packer.pack(tmp_path / "out")

    cache = ArtifactCache(cache_root=tmp_path / "cache")
    cache.get_or_extract(artifact_path)
    removed = cache.purge()
    assert removed >= 1


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def test_cli_pack_parser():
    from light_server.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["pack", "--help"])
    assert exc_info.value.code == 0


def test_cli_unpack_parser():
    from light_server.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["unpack", "--help"])
    assert exc_info.value.code == 0


def test_cli_pack_invocation(sample_model_dir: Path, tmp_path: Path):
    from light_server.cli import main

    out_dir = tmp_path / "artifacts"
    code = main([
        "pack",
        str(sample_model_dir),
        "--version", "1.0.0",
        "--output", str(out_dir),
    ])
    assert code == 0
    artifacts = list(out_dir.glob("*.lma"))
    assert len(artifacts) == 1


def test_cli_unpack_invocation(sample_model_dir: Path, tmp_path: Path):
    from light_server.cli import main

    out_dir = tmp_path / "artifacts"
    main(["pack", str(sample_model_dir), "--version", "1.0.0", "--output", str(out_dir)])
    artifact = list(out_dir.glob("*.lma"))[0]

    extract_dir = tmp_path / "extracted"
    code = main(["unpack", str(artifact), "--to", str(extract_dir)])
    assert code == 0
    assert (extract_dir / "test_model" / "1" / "model.py").exists()


def test_cli_unpack_dry_run(sample_model_dir: Path, tmp_path: Path):
    from light_server.cli import main

    out_dir = tmp_path / "artifacts"
    main(["pack", str(sample_model_dir), "--version", "1.0.0", "--output", str(out_dir)])
    artifact = list(out_dir.glob("*.lma"))[0]

    code = main(["unpack", str(artifact), "--dry-run"])
    assert code == 0
