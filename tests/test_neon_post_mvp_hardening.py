from __future__ import annotations

import copy

import pytest

from src.neon_rls import RLSNeonBackend, clear_rls_context, set_tenant_context
from src.neon_rls_storage import RLSNeonReceiptStore
from src.neon_storage import NeonBackend
from src.receipt_store import ReceiptConflictError


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return copy.deepcopy(self._row)


class _Connection:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return _Cursor(None)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _ReceiptConnection:
    def __init__(self, backend, tenant_id):
        self.backend = backend
        self.tenant_id = tenant_id

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("INSERT INTO verification_receipts"):
            verification_id, payload_sha256, payload_json, tenant_id = params
            if verification_id in self.backend.rows:
                return _Cursor(None)
            self.backend.rows[verification_id] = {
                "payload_sha256": payload_sha256,
                "payload_json": payload_json,
                "tenant_id": tenant_id,
            }
            return _Cursor({"verification_id": verification_id})
        if normalized.startswith("SELECT payload_sha256,tenant_id FROM verification_receipts"):
            verification_id = params[0]
            row = self.backend.rows.get(verification_id)
            if row is None or row["tenant_id"] != self.tenant_id:
                return _Cursor(None)
            return _Cursor({
                "payload_sha256": row["payload_sha256"],
                "tenant_id": row["tenant_id"],
            })
        raise AssertionError(f"unexpected SQL: {normalized}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _ReceiptBackend:
    def __init__(self):
        self.rows = {}

    def connect(self, *, tenant_id=None, operator=False):
        assert operator is False
        return _ReceiptConnection(self, tenant_id)


def test_rls_backend_accepts_inherited_connect_arguments_without_operator_guc(monkeypatch):
    connection = _Connection()
    monkeypatch.setattr(NeonBackend, "connect", lambda self: connection)
    backend = RLSNeonBackend("postgresql://runtime.invalid/db")

    clear_rls_context()
    returned = backend.connect(tenant_id="tenant_a", operator=True)

    assert returned is connection
    assert any("gaialab.tenant_id" in sql for sql, _ in connection.statements)
    assert all("gaialab.operator_mode" not in sql for sql, _ in connection.statements)
    assert connection.statements[-1][1] == ("tenant_a",)


def test_rls_backend_rejects_explicit_tenant_that_conflicts_with_context(monkeypatch):
    connection = _Connection()
    monkeypatch.setattr(NeonBackend, "connect", lambda self: connection)
    backend = RLSNeonBackend("postgresql://runtime.invalid/db")

    clear_rls_context()
    set_tenant_context("tenant_a")
    try:
        with pytest.raises(ValueError, match="does not match active RLS context"):
            backend.connect(tenant_id="tenant_b")
    finally:
        clear_rls_context()


def test_rls_receipt_store_is_atomic_and_idempotent_for_same_content():
    backend = _ReceiptBackend()
    store = RLSNeonReceiptStore(backend)
    envelope = {"verification_receipt": {"verification_id": "vr_same"}, "signature": {}}

    assert store.save("vr_same", envelope, tenant_id="tenant_a") is True
    assert store.save("vr_same", envelope, tenant_id="tenant_a") is False
    assert len(backend.rows) == 1


def test_rls_receipt_store_rejects_same_id_with_different_content():
    backend = _ReceiptBackend()
    store = RLSNeonReceiptStore(backend)

    assert store.save("vr_conflict", {"value": 1}, tenant_id="tenant_a") is True
    with pytest.raises(ReceiptConflictError, match="different content"):
        store.save("vr_conflict", {"value": 2}, tenant_id="tenant_a")


def test_rls_receipt_cross_tenant_collision_fails_closed_without_owner_disclosure():
    backend = _ReceiptBackend()
    store = RLSNeonReceiptStore(backend)

    assert store.save("vr_shared", {"value": 1}, tenant_id="tenant_a") is True
    with pytest.raises(ReceiptConflictError) as exc_info:
        store.save("vr_shared", {"value": 1}, tenant_id="tenant_b")

    assert "tenant_a" not in str(exc_info.value)
    assert backend.rows["vr_shared"]["tenant_id"] == "tenant_a"
