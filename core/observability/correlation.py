"""
core/observability/correlation.py
Request-scoped correlation ID propagation.

The API middleware assigns each request a correlation ID (``X-Request-ID``).
To thread that ID into code that runs deep in the call stack — notably the
orchestrator's audit writes — without adding a parameter to every function, we
store it in a ``contextvars.ContextVar``. ContextVars are the standard,
async-safe way to carry request-scoped state in Python: each asyncio task sees
its own value, so concurrent requests never leak IDs into each other.

Anything with no active request (e.g. a webhook-triggered scan, a CLI run) gets
the default ``"-"`` sentinel, which is a valid, searchable value.
"""
from __future__ import annotations

import contextvars

_DEFAULT = "-"

_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "concord_correlation_id", default=_DEFAULT
)


def set_correlation_id(value: str) -> contextvars.Token:
    """Set the current correlation ID; returns a token to reset it."""
    return _correlation_id.set(value or _DEFAULT)


def get_correlation_id() -> str:
    """Return the current correlation ID, or '-' when none is set."""
    return _correlation_id.get()


def reset_correlation_id(token: contextvars.Token) -> None:
    """Restore the previous correlation ID using the token from set()."""
    _correlation_id.reset(token)