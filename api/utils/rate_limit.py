"""
Simple Redis-backed rate limiter for sensitive endpoints.
Fails open (allows request) if Redis is unavailable, but logs a warning.

Toggle with env RATE_LIMIT_ENABLED=false for local development.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request, status

from api.utils.settings import settings

logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def rate_limit(
    request: Request,
    *,
    key_prefix: str,
    limit: int = 10,
    window_seconds: int = 60,
    identity: Optional[str] = None,
) -> None:
    """
    Allow at most `limit` hits per `window_seconds` for identity (or IP).

    No-op when RATE_LIMIT_ENABLED=false (dev switch).
    """
    if not settings.RATE_LIMIT_ENABLED:
        return

    ident = identity or _client_ip(request)
    redis_key = f"rl:{key_prefix}:{ident}"

    try:
        from api.utils.redis_utils import redis_client as redis_wrapper

        raw = getattr(redis_wrapper, "redis_client", None)
        if raw is None:
            return

        count = raw.incr(redis_key)
        if count == 1:
            raw.expire(redis_key, window_seconds)
        if count > limit:
            ttl = raw.ttl(redis_key) or window_seconds
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Retry in {ttl} seconds.",
                headers={"Retry-After": str(ttl)},
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Rate limit unavailable: %s", e)
