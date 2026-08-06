"""Clerk JWT auth for FastAPI (Bearer header or ?token= for SSE)."""

from __future__ import annotations

import logging
from typing import Annotated, Optional

import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from jwt import PyJWKClient

from app.config import get_settings

logger = logging.getLogger(__name__)

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient | None:
    global _jwks_client
    settings = get_settings()
    if not settings.clerk_jwks_url:
        return None
    if _jwks_client is None:
        _jwks_client = PyJWKClient(settings.clerk_jwks_url, cache_keys=True)
    return _jwks_client


def _extract_token(request: Request, token: Optional[str] = None) -> Optional[str]:
    if token:
        return token
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def decode_clerk_token(token: str) -> dict:
    """Decode + verify Clerk session JWT. Returns claims (sub = user id)."""
    settings = get_settings()

    if settings.clerk_dev_bypass:
        return jwt.decode(token, options={"verify_signature": False})

    jwks = _get_jwks_client()
    if jwks is None:
        # Fallback: decode without verify if JWKS not configured (warn once)
        logger.warning(
            "CLERK_JWKS_URL not set — decoding JWT without signature verification. "
            "Set CLERK_JWKS_URL for production."
        )
        return jwt.decode(token, options={"verify_signature": False})

    signing_key = jwks.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        options={"verify_aud": False},
    )


async def require_auth(
    request: Request,
    token: Annotated[Optional[str], Query()] = None,
) -> str:
    """Require authenticated user; returns Clerk user_id."""
    raw = _extract_token(request, token)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    try:
        claims = decode_clerk_token(raw)
        user_id = claims.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return str(user_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Auth failed: %s", e)
        raise HTTPException(status_code=401, detail="Unauthorized") from e


async def optional_auth(
    request: Request,
    token: Annotated[Optional[str], Query()] = None,
) -> Optional[str]:
    """Optional auth for SSE streams that may pass ?token=."""
    raw = _extract_token(request, token)
    if not raw:
        return None
    try:
        claims = decode_clerk_token(raw)
        return str(claims.get("sub")) if claims.get("sub") else None
    except Exception:
        return None
