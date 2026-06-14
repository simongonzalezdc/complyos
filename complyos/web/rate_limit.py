"""In-process rate limiting for the remote mutating API v1 surface (WP12b).

Deployment posture is customer-hosted / local-first single-tenant, so this is a
deliberately simple in-process fixed-window limiter — no Redis or external
datastore. It is meant to blunt accidental floods and trivial abuse of the
mutating PII surface, not to be a distributed quota service.

Design
------
- Only mutating methods (POST/PUT/PATCH/DELETE) on ``/api/v1/*`` are counted.
  Read-only GET/HEAD/OPTIONS pass through untouched.
- The limit is keyed on ``(identity, path_template, method)`` where ``identity``
  is the bearer token if present, else the client IP. Including the route's path
  template (e.g. ``/api/v1/imports/{batch_id}/promote``) means one endpoint's
  traffic does not starve another, while path params still share a bucket.
- Configured via ``COMPLYOS_RATE_LIMIT_PER_MINUTE``. Unset / empty / ``<= 0``
  means *effectively unlimited* so normal local dev and the existing test suite
  never trip it. Set it to a low value to enforce a real cap.
- On exceed, callers get HTTP 429 with the project structured-error shape and a
  ``Retry-After`` header (seconds until the current window rolls over).

State is process-global and reset between tests via :func:`reset_rate_limiter`.
"""

from __future__ import annotations

import os
import time
from threading import Lock

from fastapi import Request

WINDOW_SECONDS = 60
RATE_LIMIT_ENV = "COMPLYOS_RATE_LIMIT_PER_MINUTE"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Process-global fixed-window state: key -> (window_start_epoch, count).
_lock = Lock()
_buckets: dict[str, tuple[float, int]] = {}


class RateLimitExceededError(Exception):
    """Raised when a caller exceeds the configured per-minute mutating quota."""

    def __init__(self, *, limit: int, retry_after: int) -> None:
        self.limit = limit
        self.retry_after = retry_after
        super().__init__(f"rate limit of {limit}/min exceeded")


def reset_rate_limiter() -> None:
    """Clear all limiter state. Tests call this to stay isolated."""
    with _lock:
        _buckets.clear()


def _configured_limit() -> int:
    """Return the per-minute cap; ``0`` means unlimited (unset/invalid/<=0)."""
    raw = os.getenv(RATE_LIMIT_ENV, "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return 0
    return value if value > 0 else 0


def _identity(request: Request) -> str:
    """Identify the caller: bearer token if present, else client IP."""
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return f"token:{authorization[len('bearer '):].strip()}"
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


def _path_group(request: Request) -> str:
    """The matched route template, so path params share one bucket."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or request.url.path


def check_rate_limit(request: Request) -> None:
    """Enforce the mutating-endpoint quota for ``request``.

    No-op for read-only methods and when the limit is unset/unlimited. Raises
    :class:`RateLimitExceededError` once the caller exceeds the window's quota.
    """
    if request.method.upper() not in _MUTATING_METHODS:
        return

    limit = _configured_limit()
    if limit <= 0:
        return

    key = f"{_identity(request)}|{_path_group(request)}|{request.method.upper()}"
    now = time.monotonic()
    with _lock:
        window_start, count = _buckets.get(key, (now, 0))
        if now - window_start >= WINDOW_SECONDS:
            window_start, count = now, 0
        if count >= limit:
            retry_after = max(1, int(WINDOW_SECONDS - (now - window_start)))
            raise RateLimitExceededError(limit=limit, retry_after=retry_after)
        _buckets[key] = (window_start, count + 1)
