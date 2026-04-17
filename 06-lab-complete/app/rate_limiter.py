"""Sliding Window Rate Limiter"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from fastapi import HTTPException

from app.config import settings


_windows: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str) -> None:
    now = time.time()
    window = _windows[key]
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= settings.rate_limit_per_minute:
        oldest = window[0]
        retry_after = int(oldest + 60 - now) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} req/min",
            headers={
                "X-RateLimit-Limit": str(settings.rate_limit_per_minute),
                "X-RateLimit-Remaining": "0",
                "Retry-After": str(retry_after),
            },
        )
    window.append(now)
