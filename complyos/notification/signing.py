"""Canonical HMAC signing for ComplyOS webhooks.

A single implementation of the timestamped HMAC scheme shared by the outbound
signer (notification outbox) and the inbound verifier (inbound hooks). Keeping
one source of truth means the signer and verifier provably agree on the signed
bytes, so the two cannot silently drift apart and start rejecting each other's
payloads (or accepting forgeries).
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


def sign_payload(secret: str, *, timestamp: str, body: bytes) -> str:
    """Return ``sha256=<hexdigest>`` HMAC-SHA256 over ``timestamp + "." + body``."""
    signed = timestamp.encode("utf-8") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: str, *, timestamp: str, body: bytes, signature: str) -> bool:
    """Constant-time check of ``signature`` against the expected signature."""
    expected = sign_payload(secret, timestamp=timestamp, body=body)
    return hmac.compare_digest(expected, signature)
