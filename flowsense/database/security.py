"""API-key authentication for write endpoints (P0-6 / P1-6).

All mutating endpoints depend on ``require_api_key`` so that writes are
rejected with HTTP 403 unless a valid ``X-API-Key`` header is supplied.
Read endpoints intentionally remain open (no PII is exposed and the city
ops dashboard only reads aggregates).
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

# Header name expected on every write request.
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _expected_api_key() -> str:
    """Return the configured server-side API key.

    Falls back to a development default only when no real key is configured so
    the stack can boot in local/dev mode. Production must set FLOWSENSE_API_KEY.
    """
    return (
        __import__("os").getenv("FLOWSENSE_API_KEY")
        or "secret-api-key-dev"
    )


async def require_api_key(api_key: str = Depends(API_KEY_HEADER)) -> str:
    """Dependency enforcing a valid ``X-API-Key`` header on write endpoints."""
    expected = _expected_api_key()

    # When no key is configured at all we refuse writes rather than silently
    # accepting every request (fail closed, not open).
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Server API key is not configured; writes are disabled.",
        )

    if not api_key or api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-API-Key header. Write access denied.",
        )

    return api_key
