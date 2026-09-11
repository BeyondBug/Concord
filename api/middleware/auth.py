"""
api/middleware/auth.py
API-key authentication for Concord's HTTP API.

Model
-----
A single shared API key is read from the ``CONCORD_API_KEY`` environment
variable. Clients present it as a bearer token::

    Authorization: Bearer <key>

or, equivalently, via the ``X-API-Key`` header.

Fail-safe dev mode
------------------
If ``CONCORD_API_KEY`` is unset or empty, the API runs in **open dev mode**:
requests are allowed and a warning is logged once at import time. This keeps
local development frictionless while making the open state loud and explicit
rather than a silent default. In any real deployment, set ``CONCORD_API_KEY``.

Why a dependency, not a global middleware
----------------------------------------
Using a FastAPI dependency lets us protect data/state-changing routers while
leaving genuinely public endpoints (health, dashboard, and the GitHub webhook,
which has its own HMAC signature check) open. The comparison is constant-time
and the key is never logged.
"""
import hmac
import logging
import os

from fastapi import Header, HTTPException, status

logger = logging.getLogger("concord.auth")

_ENV_KEY = "CONCORD_API_KEY"

# Log the auth posture once, at import, so operators see it in startup logs.
if not os.getenv(_ENV_KEY):
    logger.warning(
        "%s is not set — API running in OPEN DEV MODE (no authentication). "
        "Set %s before exposing Concord on any network.",
        _ENV_KEY, _ENV_KEY,
    )


def _configured_key() -> str:
    return os.getenv(_ENV_KEY, "")


def _extract_presented_key(authorization: str | None,
                           x_api_key: str | None) -> str | None:
    """Pull the key from either the Authorization or X-API-Key header."""
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    return None


async def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """FastAPI dependency: enforce the API key unless in open dev mode.

    Raises 401 when a key is configured but the request's key is missing or
    wrong. Uses a constant-time comparison to avoid leaking the key via timing.
    """
    configured = _configured_key()
    if not configured:
        # Open dev mode — allow, but do not pretend a key was checked.
        return

    presented = _extract_presented_key(authorization, x_api_key)
    if not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide 'Authorization: Bearer <key>' "
                   "or 'X-API-Key: <key>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(presented, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Authenticated. Never log the key or the presented value.


def auth_is_enforced() -> bool:
    """True when a key is configured (i.e. not in open dev mode)."""
    return bool(_configured_key())