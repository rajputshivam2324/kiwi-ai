"""Simple in-memory sliding-window rate limiter."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

from app.config import get_settings


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, limit: int | None = None, window: int | None = None) -> None:
        settings = get_settings()
        limit = limit if limit is not None else settings.rate_limit_requests
        window = window if window is not None else settings.rate_limit_window_seconds
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please wait and try again.",
                )
            q.append(now)


rate_limiter = RateLimiter()


async def rate_limit_dependency(request: Request) -> None:
    """Rate-limit by client IP (and user id if set by upstream)."""
    client = request.client.host if request.client else "unknown"
    # Prefer Authorization fingerprint for authenticated routes
    auth = request.headers.get("Authorization", "")[:40]
    key = f"{client}:{auth}" if auth else client
    rate_limiter.check(key)
