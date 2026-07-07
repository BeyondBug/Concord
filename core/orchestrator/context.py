"""Context manager — sanitizes tool output before LLM injection."""


def sanitize_tool_output(raw: str) -> str:
    """Strip prompt injection vectors from tool output.

    Phase 3: implement full sanitization.
    For now: at minimum, limit length to reduce attack surface.
    """
    return raw[:4000]
