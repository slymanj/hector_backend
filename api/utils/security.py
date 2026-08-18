"""
Security helpers: safe errors, role checks, input limits.
Never log secrets, tokens, or private keys.
"""
from __future__ import annotations

import re
import logging
from typing import Optional

from fastapi import HTTPException, status

from api.utils.settings import settings

logger = logging.getLogger(__name__)

# Patterns that should never appear in client-facing errors or logs
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN[^-]+-----[\s\S]*?-----END[^-]+-----", re.I),
    re.compile(r"\b(0x)?[a-fA-F0-9]{64}\b"),  # raw hex keys
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.I),
]


def is_production() -> bool:
    return (settings.ENVIRONMENT or "").lower() in ("production", "prod", "staging")


def safe_error_detail(exc: Exception, public_message: str = "Request failed") -> str:
    """
    Return a client-safe error string.
    In production, hide internal exception text to avoid info leaks.
    """
    if is_production():
        logger.error("%s: %s: %s", public_message, type(exc).__name__, exc)
        return public_message
    # Dev: still scrub obvious secret material
    msg = str(exc)
    for pat in _SECRET_PATTERNS:
        msg = pat.sub("[REDACTED]", msg)
    return msg or public_message


def require_roles(user, *allowed: str) -> None:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )


def sanitize_log_message(message: str) -> str:
    out = message
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def validate_password_strength(password: str) -> None:
    """Stronger password rules for investment platform accounts."""
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters long")
    if not re.search(r"[A-Za-z]", password):
        raise ValueError("Password must contain at least one letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one number")
