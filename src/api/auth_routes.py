# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Auth routes: license key → JWT + VN magic-link auth.

Legacy license-key routes (for IDE):
  POST /auth/login   {license_key} → {access_token, refresh_token, expires_in, tenant_id, tier}
  POST /auth/refresh {refresh_token} → {access_token, refresh_token, token_type, expires_in, tenant_id, tier}

VN Hub magic-link routes (public, enumeration-safe):
  POST /v1/auth/magic-link  {email, purpose?} → 200 always (rate-limited)
  GET  /v1/auth/verify?token=...              → 200 {jwt, scopes, allowed_orgs}
                                               or 401 {error: invalid_or_expired_link}
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from typing import Optional

import jwt
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from engine.license.license_store import get_license_store
from src.services import magic_link_service, resend_client
from src.services.audit_logger import audit_admin_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

ACCESS_TOKEN_TTL_SECONDS = 60 * 60  # 1 hour
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
JWT_ALGORITHM = "HS256"


class LoginRequest(BaseModel):
    license_key: str = Field(..., min_length=8, max_length=512)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_in: int
    tenant_id: str
    tier: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10, max_length=1024)


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    tenant_id: str
    tier: str


def _jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"):
            return "dev-test-secret-only"
        raise RuntimeError("JWT_SECRET env var is required")
    return secret


def _issue_token(tenant_id: str, license_key: str, tier: str) -> tuple[str, int]:
    now = int(time.time())
    exp = now + ACCESS_TOKEN_TTL_SECONDS
    payload = {
        "tenant_id": tenant_id,
        "license_key": license_key,
        "tier": tier,
        "token_type": "access",
        "iat": now,
        "exp": exp,
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, ACCESS_TOKEN_TTL_SECONDS


def _issue_refresh_token(tenant_id: str, license_key: str, tier: str) -> tuple[str, int]:
    now = int(time.time())
    exp = now + REFRESH_TOKEN_TTL_SECONDS
    payload = {
        "tenant_id": tenant_id,
        "license_key": license_key,
        "tier": tier,
        "token_type": "refresh",
        "iat": now,
        "exp": exp,
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, REFRESH_TOKEN_TTL_SECONDS


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest) -> LoginResponse:
    store = get_license_store()
    record = store.get(req.license_key)
    if not record:
        raise HTTPException(status_code=401, detail={"error": "invalid_license"})

    if record.get("status") != "active":
        raise HTTPException(status_code=402, detail={"error": "license_inactive"})

    tenant_id = record.get("customer_id")
    tier = record.get("tier", "starter")
    if not tenant_id:
        raise HTTPException(status_code=500, detail={"error": "license_missing_tenant"})

    token, ttl = _issue_token(tenant_id, req.license_key, tier)
    refresh_token, _ = _issue_refresh_token(tenant_id, req.license_key, tier)
    logger.info("auth.login_success", extra={"tenant_id": tenant_id, "tier": tier})
    return LoginResponse(
        access_token=token,
        refresh_token=refresh_token,
        expires_in=ttl,
        tenant_id=tenant_id,
        tier=tier,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(req: RefreshRequest) -> RefreshResponse:
    try:
        claims = jwt.decode(req.refresh_token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail={"error": "token_expired"})
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail={"error": "invalid_token"})

    token_type = claims.get("token_type")
    if token_type != "refresh":
        raise HTTPException(status_code=401, detail={"error": "invalid_token_type"})

    license_key = claims.get("license_key")
    tenant_id = claims.get("tenant_id")
    if not license_key or not tenant_id:
        raise HTTPException(status_code=401, detail={"error": "malformed_claims"})

    store = get_license_store()
    record = store.get(license_key)
    if not record:
        raise HTTPException(status_code=401, detail={"error": "invalid_license"})

    if record.get("status") != "active":
        raise HTTPException(status_code=402, detail={"error": "license_inactive"})

    # Dynamic tier resolution from license record (reflecting any upgrades)
    current_tier = record.get("tier", claims.get("tier", "starter"))
    record_tenant = record.get("customer_id")
    if record_tenant:
        tenant_id = record_tenant

    new_access_token, ttl = _issue_token(tenant_id, license_key, current_tier)
    new_refresh_token, _ = _issue_refresh_token(tenant_id, license_key, current_tier)
    logger.info(
        "auth.refresh_success",
        extra={"tenant_id": tenant_id, "tier": current_tier},
    )
    return RefreshResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="Bearer",
        expires_in=ttl,
        tenant_id=tenant_id,
        tier=current_tier,
    )


# =============================================================================
# VN HUB — Magic-Link Auth Routes (prefix: /v1/auth)
# =============================================================================

vn_auth_router = APIRouter(prefix="/v1/auth", tags=["VN Magic-Link Auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_MEKONG_PUBLIC_BASE_URL_DEFAULT = "https://api.mekong.dev"


class MagicLinkRequest(BaseModel):
    email: str = Field(..., max_length=320)
    purpose: str = Field(default="login", max_length=32)


class MagicLinkResponse(BaseModel):
    ok: bool
    message: str


class VerifyResponse(BaseModel):
    ok: bool
    jwt: str
    expires_at: str
    scopes: list[str]
    allowed_orgs: list[str]


def _send_magic_link_bg(email: str, token: str, purpose: str) -> None:
    """Background task: send magic-link email via Resend. Never raises."""
    base_url = os.getenv("MEKONG_PUBLIC_BASE_URL", _MEKONG_PUBLIC_BASE_URL_DEFAULT)
    magic_url = f"{base_url}/v1/auth/verify?token={token}"
    try:
        resend_client.send_magic_link_email(email, magic_url, purpose)
        audit_admin_action(
            scope="magic_link.sent",
            org="none",
            sub=email,
            endpoint="/v1/auth/magic-link",
        )
        logger.info("magic_link.sent", extra={"email": email, "purpose": purpose})
    except Exception as exc:
        # Fire-and-forget: log failure but never surface to caller
        logger.error(
            "magic_link.send_failed",
            extra={"email": email, "purpose": purpose, "error": str(exc)},
        )
        print(
            f"[magic_link] WARN: email send failed for {email}: {exc}",
            file=sys.stderr,
        )


@vn_auth_router.post("/magic-link", response_model=MagicLinkResponse)
async def request_magic_link(
    req: MagicLinkRequest,
    background_tasks: BackgroundTasks,
) -> MagicLinkResponse:
    """Mint a magic-link token and send email (enumeration-safe).

    Always returns 200 regardless of whether the email exists.
    Rate-limit: 5 tokens/email/hour — over-cap requests are silently dropped.
    Email is sent as a BackgroundTask — mint endpoint never blocks on Resend.
    """
    _OK_RESPONSE = MagicLinkResponse(
        ok=True,
        message="Nếu email tồn tại, liên kết đăng nhập đã được gửi.",
    )

    # Validate email format
    if not _EMAIL_RE.match(req.email):
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_email_format"},
        )

    # Rate limit check — silently drop if over cap
    if not magic_link_service.check_rate_limit(req.email):
        logger.warning(
            "magic_link.rate_limited", extra={"email": req.email}
        )
        audit_admin_action(
            scope="magic_link.rate_limited",
            org="none",
            sub=req.email,
            endpoint="/v1/auth/magic-link",
        )
        return _OK_RESPONSE  # enumeration-safe: same response as success

    # Mint token and schedule email send in background
    token = magic_link_service.mint_token(req.email, req.purpose)
    background_tasks.add_task(_send_magic_link_bg, req.email, token, req.purpose)

    audit_admin_action(
        scope="magic_link.minted",
        org="none",
        sub=req.email,
        endpoint="/v1/auth/magic-link",
    )
    return _OK_RESPONSE


@vn_auth_router.get("/verify", response_model=VerifyResponse)
async def verify_magic_link(
    token: str = Query(..., min_length=10, max_length=128),
) -> VerifyResponse:
    """Verify magic-link token and mint 24h JWT.

    Single-use: atomically marks redeemed_at on success.
    Any invalid/expired/reused token returns 401 with single error code
    (no information leak about token state).
    """
    try:
        result = magic_link_service.verify_and_redeem(token)
    except (
        magic_link_service.MagicLinkInvalid,
        magic_link_service.MagicLinkExpired,
        magic_link_service.MagicLinkAlreadyRedeemed,
    ):
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_or_expired_link"},
        )

    email = result["email"]
    purpose = result["purpose"]

    jwt_token, expires_at = magic_link_service.mint_jwt_for_email(email)

    # Decode to extract scopes/orgs for response (no re-verify needed — we just minted)
    import jwt as _jwt
    secret = os.getenv("MEKONG_JWT_SECRET", "")
    try:
        claims = _jwt.decode(jwt_token, secret, algorithms=["HS256"])
    except Exception:
        claims = {}

    scopes = claims.get("scopes", ["none"])
    allowed_orgs = claims.get("allowed_orgs", [])

    audit_admin_action(
        scope="magic_link.verified",
        org=allowed_orgs[0] if allowed_orgs else "none",
        sub=email,
        endpoint="/v1/auth/verify",
    )
    logger.info(
        "magic_link.verified",
        extra={"email": email, "purpose": purpose, "scopes": scopes},
    )

    return VerifyResponse(
        ok=True,
        jwt=jwt_token,
        expires_at=expires_at,
        scopes=scopes,
        allowed_orgs=allowed_orgs,
    )
