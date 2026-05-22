"""Ed25519 signing and verification for artifact manifests."""

from __future__ import annotations

import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from light_server.artifact.manifest import Manifest


def generate_keypair() -> tuple[bytes, bytes]:
    """Generate a new Ed25519 keypair.

    Returns:
        (private_key_pem, public_key_pem) both as bytes.
    """
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def sign_manifest(manifest: Manifest, private_key_pem: bytes, signer: str = "") -> None:
    """Sign a manifest in-place using Ed25519.

    The manifest is canonicalised to sorted JSON and signed. The signature
    field on the manifest is updated.
    """
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("Private key must be an Ed25519 key")

    payload = manifest.to_canonical_json().encode("utf-8")
    signature_bytes = private_key.sign(payload)

    manifest.signature = manifest.signature.__class__(
        alg="ed25519",
        value=base64.b64encode(signature_bytes).decode("ascii"),
        signer=signer or manifest.signature.signer,
    )


def verify_manifest(manifest: Manifest, public_key_pem: bytes) -> bool:
    """Verify the manifest signature against an Ed25519 public key.

    Returns True if valid, False if missing or invalid.
    """
    if not manifest.signature.value or manifest.signature.alg != "ed25519":
        return False

    public_key = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(public_key, Ed25519PublicKey):
        raise TypeError("Public key must be an Ed25519 key")

    # Build a copy of the manifest without the signature for verification
    from light_server.artifact.manifest import Manifest as ManifestCls

    payload_manifest = ManifestCls(
        manifest_version=manifest.manifest_version,
        name=manifest.name,
        version=manifest.version,
        build_id=manifest.build_id,
        created_at=manifest.created_at,
        entrypoint=manifest.entrypoint,
        files=manifest.files,
        metadata=manifest.metadata,
    )
    payload = payload_manifest.to_canonical_json().encode("utf-8")
    signature_bytes = base64.b64decode(manifest.signature.value)

    try:
        public_key.verify(signature_bytes, payload)
        return True
    except InvalidSignature:
        return False
