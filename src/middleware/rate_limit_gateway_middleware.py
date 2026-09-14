# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Rate limit gateway middleware — wires existing RateLimiter into FastAPI.

Maps path patterns to RateLimitPreset, extracts client IP, returns 429
with X-RateLimit-* headers when limit exceeded.
Skips /health, /healthz, /metrics.

Activation: set RATE_LIMIT_ENABLED=1 (disabled by default so test suites
running many requests against the same IP do not exhaust in-memory buckets).
"""
from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from src.auth.rate_limiter import RateLimitPreset, get_rate_limiter

_RATE_LIMIT_ACTIVE = os.getenv("RATE_LIMIT_ENABLED", "0") == "1"
_SKIP_PATHS = {"/health", "/healthz", "/metrics"}


def _resolve_preset(method: str, path: str) -> RateLimitPreset:
    """Map request method/path to the appropriate rate limit preset."""
    if path in ("/auth/refresh", "/v1/auth/refresh"):
        return RateLimitPreset.AUTH_REFRESH
    if path.startswith("/v1/auth/") or path.startswith("/auth/"):
        return RateLimitPreset.AUTH_LOGIN
    if method in ("POST", "PUT", "DELETE", "PATCH"):
        return RateLimitPreset.API_WRITE
    if method == "GET":
        return RateLimitPreset.API_READ
    return RateLimitPreset.API_DEFAULT


class RateLimitGatewayMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting middleware using the existing RateLimiter singleton."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: object) -> Response:  # type: ignore[override]
        if not _RATE_LIMIT_ACTIVE:
            return await call_next(request)  # type: ignore[misc]

        path = request.url.path

        if path in _SKIP_PATHS:
            return await call_next(request)  # type: ignore[misc]

        client_ip = (request.client.host if request.client else "unknown")
        method = request.method.upper()
        preset = _resolve_preset(method, path)
        key = f"{client_ip}:{path}"

        limiter = get_rate_limiter()
        allowed, headers = await limiter.check_limit(key=key, preset=preset)

        if not allowed:
            return JSONResponse(
                {"error": "rate_limit_exceeded", "retry_after": headers.get("Retry-After")},
                status_code=429,
                headers=headers,
            )

        response: Response = await call_next(request)  # type: ignore[misc]
        # Attach rate limit headers to successful responses too
        for header_name, header_value in headers.items():
            response.headers[header_name] = header_value
        return response
