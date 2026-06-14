"""Direct unit tests for the inbound webhook ingestion boundary (WP3).

InboundHookService accepts arbitrary external bodies, validates HMAC, enforces
freshness, and redacts secrets before persistence. These branches previously
had no direct coverage, so a refactor flipping fail-closed to fail-open (or
dropping redaction) would not have failed any test.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from complyos.core.repository import LocalRepository
from complyos.notification.signing import sign_payload
from complyos.services.context import default_local_context
from complyos.services.inbound_hooks import InboundHookService, InboundWebhookSignatureError

SECRET = "inbound-secret"


def _service(tmp_path, name="inbound.db"):
    repo = LocalRepository(str(tmp_path / name))
    return InboundHookService(repo), repo


def _context(tenant_id="tenant-a"):
    return default_local_context(tenant_id=tenant_id, role="compliance_manager")


def _signed_headers(body: bytes, *, timestamp: str | None = None) -> dict[str, str]:
    ts = timestamp or datetime.now(UTC).isoformat()
    return {
        "X-ComplyOS-Timestamp": ts,
        "X-ComplyOS-Signature": sign_payload(SECRET, timestamp=ts, body=body),
        "Content-Type": "application/json",
    }


def test_valid_signature_stores_redacted_receipt(tmp_path) -> None:
    service, _ = _service(tmp_path)
    body = json.dumps(
        {"event_type": "lms.updated", "object_id": "a1", "api_token": "do-not-store"},
        separators=(",", ":"),
    ).encode("utf-8")

    stored = service.record(
        _context(),
        source="canvas",
        body=body,
        headers=_signed_headers(body),
        signing_secret=SECRET,
    )

    assert stored["signature_valid"] is True
    assert stored["event_type"] == "lms.updated"
    # The credential-shaped key is stripped before persistence.
    assert "api_token" not in stored["payload"]


def test_missing_signature_headers_are_rejected_when_secret_configured(tmp_path) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(InboundWebhookSignatureError, match="missing inbound webhook signature"):
        service.record(
            _context(),
            source="canvas",
            body=b"{}",
            headers={"Content-Type": "application/json"},
            signing_secret=SECRET,
        )


def test_stale_timestamp_is_rejected(tmp_path) -> None:
    service, _ = _service(tmp_path)
    body = b'{"event_type":"lms.updated"}'
    stale = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with pytest.raises(InboundWebhookSignatureError, match="tolerance window"):
        service.record(
            _context(),
            source="canvas",
            body=body,
            headers=_signed_headers(body, timestamp=stale),
            signing_secret=SECRET,
        )


def test_tampered_signature_is_rejected(tmp_path) -> None:
    service, _ = _service(tmp_path)
    body = b'{"event_type":"lms.updated"}'
    headers = _signed_headers(body)
    headers["X-ComplyOS-Signature"] = "sha256=deadbeef"
    with pytest.raises(InboundWebhookSignatureError, match="invalid inbound webhook signature"):
        service.record(
            _context(),
            source="canvas",
            body=body,
            headers=headers,
            signing_secret=SECRET,
        )


def test_missing_secret_fails_closed_by_default(tmp_path) -> None:
    service, _ = _service(tmp_path)
    with pytest.raises(InboundWebhookSignatureError, match="signing secret is not configured"):
        service.record(
            _context(),
            source="canvas",
            body=b"{}",
            headers={},
            signing_secret=None,
        )


def test_missing_secret_can_be_explicitly_allowed_as_untrusted(tmp_path) -> None:
    service, _ = _service(tmp_path)
    stored = service.record(
        _context(),
        source="canvas",
        body=b'{"event_type":"lms.updated"}',
        headers={},
        signing_secret=None,
        require_signature=False,
    )
    assert stored["signature_valid"] is False
    assert stored["status"] == "received"


def test_non_json_body_is_stored_as_raw_hash(tmp_path) -> None:
    service, _ = _service(tmp_path)
    body = b"\x00\x01not-json"
    stored = service.record(
        _context(),
        source="canvas",
        body=body,
        headers=_signed_headers(body),
        signing_secret=SECRET,
    )
    assert "raw_body_hash" in stored["payload"]


def test_receipts_are_tenant_scoped(tmp_path) -> None:
    service, _ = _service(tmp_path)
    body = b'{"event_type":"lms.updated"}'
    service.record(
        _context("tenant-a"),
        source="canvas",
        body=body,
        headers=_signed_headers(body),
        signing_secret=SECRET,
    )
    assert service.list_receipts(_context("tenant-a")) != []
    assert service.list_receipts(_context("tenant-b")) == []
