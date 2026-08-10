"""Externally portable signed checkpoints for the GaiaLab operator action chain.

A checkpoint binds the current operator-action stream head and action count to an
Ed25519 signature. The resulting JSON object is safe to copy outside the Trust
Rail database so later database rewriting/truncation can be detected against an
independently retained checkpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

from src.receipt_signing import sign_receipt, verify_receipt_signature

OPERATOR_CHECKPOINT_VERSION = "gaialab-naija-operator-checkpoint/0.1.0"
SUPPORTED_STREAM_ID = "global"


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _checkpoint_id(core: Mapping[str, Any]) -> str:
    return "opchk_" + hashlib.sha256(_canonical_json(core).encode("utf-8")).hexdigest()[:32]


def create_checkpoint(
    action_log: Any,
    private_key_b64: str,
    *,
    stream_id: str = SUPPORTED_STREAM_ID,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Create a signed, portable checkpoint from a verified action-log state."""
    if stream_id != SUPPORTED_STREAM_ID:
        raise ValueError("only the global operator action stream is supported")
    integrity = action_log.verify_chain()
    if not integrity.get("valid"):
        raise ValueError(f"operator action chain is not valid: {integrity.get('reason')}")
    count = int(integrity.get("count", 0))
    head = str(integrity.get("head") or "")
    if len(head) != 64:
        raise ValueError("operator action chain head is invalid")

    core = {
        "version": OPERATOR_CHECKPOINT_VERSION,
        "stream_id": SUPPORTED_STREAM_ID,
        "action_count": count,
        "action_head_sha256": head,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
    }
    checkpoint = {"checkpoint_id": _checkpoint_id(core), **core}
    signature = sign_receipt(checkpoint, private_key_b64)
    return {"checkpoint": checkpoint, "signature": signature}


def verify_checkpoint(
    package: Mapping[str, Any],
    *,
    expected_key_id: str | None = None,
) -> dict[str, Any]:
    """Verify checkpoint structure, content binding, and Ed25519 signature."""
    checkpoint = dict(package.get("checkpoint") or {})
    signature = dict(package.get("signature") or {})
    if checkpoint.get("version") != OPERATOR_CHECKPOINT_VERSION:
        return {"valid": False, "reason": "unsupported_checkpoint_version"}
    try:
        stream_id = str(checkpoint["stream_id"])
        action_count = int(checkpoint["action_count"])
        head = str(checkpoint["action_head_sha256"])
        created_at = str(checkpoint["created_at"])
    except (KeyError, TypeError, ValueError):
        return {"valid": False, "reason": "invalid_checkpoint_shape"}
    if stream_id != SUPPORTED_STREAM_ID:
        return {"valid": False, "reason": "unsupported_checkpoint_stream"}
    if action_count < 0 or len(head) != 64 or not created_at:
        return {"valid": False, "reason": "invalid_checkpoint_shape"}

    core = {
        "version": checkpoint["version"],
        "stream_id": stream_id,
        "action_count": action_count,
        "action_head_sha256": head,
        "created_at": created_at,
    }
    if checkpoint.get("checkpoint_id") != _checkpoint_id(core):
        return {"valid": False, "reason": "checkpoint_id_mismatch"}

    signature_result = verify_receipt_signature(checkpoint, signature)
    if not signature_result.get("valid"):
        return {"valid": False, "reason": signature_result.get("reason", "invalid_signature")}
    if expected_key_id is not None and signature_result.get("key_id") != expected_key_id:
        return {"valid": False, "reason": "unexpected_signing_key", "key_id": signature_result.get("key_id")}
    return {
        "valid": True,
        "reason": "checkpoint_signature_valid",
        "checkpoint_id": checkpoint["checkpoint_id"],
        "key_id": signature_result.get("key_id"),
        "action_count": action_count,
        "action_head_sha256": head,
    }


def verify_checkpoint_against_log(
    package: Mapping[str, Any],
    action_log: Any,
    *,
    expected_key_id: str | None = None,
) -> dict[str, Any]:
    """Verify a signed checkpoint and compare it with the current action chain."""
    signed = verify_checkpoint(package, expected_key_id=expected_key_id)
    if not signed.get("valid"):
        return signed
    current = action_log.verify_chain()
    if not current.get("valid"):
        return {"valid": False, "reason": "current_operator_chain_invalid", "chain_reason": current.get("reason")}

    checkpoint = package["checkpoint"]
    checkpoint_count = int(checkpoint["action_count"])
    current_count = int(current.get("count", 0))
    checkpoint_head = str(checkpoint["action_head_sha256"])
    current_head = str(current.get("head") or "")

    if current_count < checkpoint_count:
        return {
            "valid": False,
            "reason": "operator_chain_truncated_since_checkpoint",
            "checkpoint_count": checkpoint_count,
            "current_count": current_count,
        }
    if current_count == checkpoint_count and current_head != checkpoint_head:
        return {
            "valid": False,
            "reason": "operator_chain_rewritten_since_checkpoint",
            "checkpoint_head": checkpoint_head,
            "current_head": current_head,
        }
    if current_count == checkpoint_count:
        return {**signed, "reason": "checkpoint_matches_current_chain", "current_count": current_count}

    # A later chain head cannot be compared directly to an older head without
    # examining the historical row at checkpoint_count. Require list() support
    # and bind the checkpoint to the exact action at that position.
    rows = action_log.list(limit=current_count)
    if checkpoint_count == 0:
        from src.operator_action_log import GENESIS_HASH
        historical_head = GENESIS_HASH
    elif len(rows) >= checkpoint_count:
        historical_head = str(rows[checkpoint_count - 1].get("action_hash") or "")
    else:
        return {"valid": False, "reason": "operator_chain_history_unavailable"}
    if historical_head != checkpoint_head:
        return {
            "valid": False,
            "reason": "operator_chain_history_rewritten_since_checkpoint",
            "checkpoint_head": checkpoint_head,
            "historical_head": historical_head,
        }
    return {
        **signed,
        "reason": "checkpoint_is_valid_ancestor",
        "current_count": current_count,
        "current_head": current_head,
    }
