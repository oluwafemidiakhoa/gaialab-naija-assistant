"""Ed25519 signing helpers for GaiaLab verification receipts."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, PublicFormat

SIGNATURE_VERSION = "gaialab-naija-receipt-signature/0.1.0"


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def generate_signing_keypair() -> dict[str, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        "private_key_b64": base64.b64encode(private_bytes).decode("ascii"),
        "public_key_b64": base64.b64encode(public_bytes).decode("ascii"),
        "key_id": hashlib.sha256(public_bytes).hexdigest()[:24],
    }


def sign_receipt(receipt: Mapping[str, Any], private_key_b64: str) -> dict[str, str]:
    private_bytes = base64.b64decode(private_key_b64, validate=True)
    if len(private_bytes) != 32:
        raise ValueError("Ed25519 private key must decode to exactly 32 raw bytes")
    private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    public_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    signature = private_key.sign(_canonical_bytes(receipt))
    return {
        "version": SIGNATURE_VERSION,
        "algorithm": "Ed25519",
        "key_id": hashlib.sha256(public_bytes).hexdigest()[:24],
        "public_key_b64": base64.b64encode(public_bytes).decode("ascii"),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
    }


def verify_receipt_signature(receipt: Mapping[str, Any], signature: Mapping[str, Any]) -> dict[str, Any]:
    if signature.get("algorithm") != "Ed25519":
        return {"valid": False, "reason": "unsupported_signature_algorithm"}
    try:
        public_bytes = base64.b64decode(str(signature["public_key_b64"]), validate=True)
        signature_bytes = base64.b64decode(str(signature["signature_b64"]), validate=True)
        if len(public_bytes) != 32:
            return {"valid": False, "reason": "invalid_public_key_length"}
        expected_key_id = hashlib.sha256(public_bytes).hexdigest()[:24]
        if signature.get("key_id") != expected_key_id:
            return {"valid": False, "reason": "key_id_mismatch"}
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature_bytes, _canonical_bytes(receipt))
    except (KeyError, ValueError, InvalidSignature):
        return {"valid": False, "reason": "invalid_signature"}
    return {"valid": True, "reason": "signature_valid", "key_id": expected_key_id}
