# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mekong CLI - Gateway API Server.

FastAPI server exposing Mekong CLI orchestration to AgencyOS.
REST API + SSE streaming for real-time mission execution.

Usage:
    uvicorn src.gateway:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import os as _os
import sys
import time as _time
from datetime import datetime, timezone

# ruff: noqa: E402
# sys.path must be modified before these engine/src imports

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.gateway_mission_routes import router as mission_router
from src.api.gateway_webhook_mcu_routes import router as webhook_mcu_router
from src.api.coupon_router import router as coupon_router
from src.api.auth_routes import router as auth_router, vn_auth_router
from src.auth.routes import router as auth_ui_router
from src.raas.missions_api_router import router as raas_router
from src.raas.revenue_router import router as revenue_router
from src.raas.checkout_router import router as checkout_router
from src.raas.nowpayments_router import router as nowpayments_router
from src.raas.tenant_use_case_router import router as tenant_router
from src.raas.reports_router import router as reports_router
from src.raas.autopilot import router as autopilot_router
from src.raas.marketplace_router import router as marketplace_router
from src.api.vn_pricing_routes import router as vn_pricing_router
from src.api.vn_pilot_routes import router as vn_pilot_router
from src.api.vn_payments_routes import router as vn_payments_router
from src.api.org_routes import org_router
from src.api.billing_routes import router as billing_router
from src.api.metrics_routes import router as metrics_router
from src.api.quota_status_endpoints import quota_router
from src.api.tier_config_routes import router as tier_config_router
from src.middleware.csrf_middleware import CSRFMiddleware
from src.middleware.rate_limit_gateway_middleware import RateLimitGatewayMiddleware
from src.middleware.pilot_credit_gate import PilotCreditGateMiddleware
# Ensure engine/ layer is importable regardless of uvicorn cwd
import sys as _sys
_ENGINE_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "engine")
if _ENGINE_DIR not in _sys.path:
    _sys.path.insert(0, _ENGINE_DIR)

from engine.license.license_gate_middleware import EngineLicenseGateMiddleware
from src.core.request_logger import RequestLoggerMiddleware
from src.core.mcu_billing import MCUBilling
from src.core.billing_adapter import BillingAdapter
from src.core.logging_config import configure_logging
from src.core.sentry_init import init_sentry
from src.core.telemetry_init import init_telemetry

configure_logging()
init_sentry()
init_telemetry()

logger = logging.getLogger(__name__)

# Capture process start time for uptime reporting
_APP_START_TIME: float = _time.monotonic()

# =============================================================================
# BILLING SINGLETON
# =============================================================================
# Global MCUBilling instance for credit management. Retained under the name
# `mcu_billing` because metrics_routes.py and the e2e suite reach its
# internal API (tenant_count, add_credits, _store). New code should go
# through `billing_adapter`, the canonical PaymentProvider entry point
# that wraps this same singleton.
mcu_billing = MCUBilling()
billing_adapter = BillingAdapter(mcu_billing)

# =============================================================================
# FASTAPI APP
# =============================================================================

_is_production = _os.getenv("MEKONG_ENV", "development") == "production"

app = FastAPI(
    title="Mekong CLI Gateway API",
    description="Unified API for MekongMind — the one-person company platform",
    version="3.3.0",
    docs_url=None if _is_production else "/api-docs",
    redoc_url=None if _is_production else "/api-redoc",
)

# Mount routers — gateway endpoints
app.include_router(mission_router)
app.include_router(webhook_mcu_router)
app.include_router(coupon_router)
# app.include_router(polar_webhook_router)  # LEGACY — removed
app.include_router(auth_router)
app.include_router(vn_auth_router)
app.include_router(auth_ui_router)

# Mount routers — RaaS endpoints
app.include_router(raas_router)
app.include_router(revenue_router)
app.include_router(checkout_router)
app.include_router(nowpayments_router)
app.include_router(tenant_router)
app.include_router(reports_router)
app.include_router(vn_pricing_router)
app.include_router(vn_pilot_router)
app.include_router(vn_payments_router)
app.include_router(org_router)
app.include_router(billing_router)
app.include_router(autopilot_router)
app.include_router(marketplace_router)
app.include_router(metrics_router)
app.include_router(quota_router)
app.include_router(tier_config_router)

# CORS for AgencyOS frontend
_ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in _os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://localhost:8080,https://mekongmind.com,https://www.mekongmind.com,https://api.cashclaw.cc,https://ide.mekongmind.com",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Idempotency-Key", "X-CSRF-Token"],
)
# CSRF runs after CORS (added after in source → runs before in request chain due to LIFO)
app.add_middleware(CSRFMiddleware)
# Rate limiting runs closest to handlers (added last → runs first on inbound)
app.add_middleware(RateLimitGatewayMiddleware)

# =============================================================================
# PILOT CREDIT GATE
# =============================================================================
# Soft paywall: expired/overdue pilot users get HTTP 402 + VietQR payment
# instructions on credit-consuming routes. Skips payment/health endpoints
# so expired users can always see how to pay. Only activates when
# MEKONG_PILOT_GATE=1.
app.add_middleware(PilotCreditGateMiddleware)

# =============================================================================
# ENGINE LICENSE GATE
# =============================================================================
# Runtime tier enforcement backed by engine/license/LICENSE enforcer.
# Disabled by default (minimum_tier defaults to FREE).
# Set MEKONG_MINIMUM_TIER=BASIC|PRO|ENTERPRISE to activate.
app.add_middleware(EngineLicenseGateMiddleware)



# =============================================================================
# HEALTH CHECK
# =============================================================================

_APP_VERSION = "3.3.0"


def _memory_usage_mb() -> float | None:
    """Return RSS memory in MB, or None if psutil unavailable."""
    try:
        import psutil
        proc = psutil.Process()
        return round(proc.memory_info().rss / 1024 / 1024, 2)
    except ImportError:
        return None


async def _check_database() -> dict:
    """Probe PostgreSQL connectivity via asyncpg pool."""
    db_url = _os.getenv("DATABASE_URL")
    if not db_url:
        return {"status": "disabled", "configured": False}
    try:
        from src.db.database import get_database
        db = get_database()
        if db._pool is None:
            return {"status": "not_connected", "configured": True}
        async with db._pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "healthy", "configured": True}
    except Exception as exc:
        return {"status": "unhealthy", "configured": True, "error": str(exc)}


def _component_status() -> dict[str, dict]:
    """Check key component availability without external I/O."""
    components: dict[str, dict] = {}

    # Billing
    try:
        _ = billing_adapter  # singleton already constructed
        components["billing"] = {"status": "healthy"}
    except Exception as exc:
        components["billing"] = {"status": "unhealthy", "error": str(exc)}

    # Auth (check module importability)
    try:
        from src.core.auth_jwt import decode_jwt  # noqa: F401
        components["auth"] = {"status": "healthy"}
    except Exception as exc:
        components["auth"] = {"status": "unhealthy", "error": str(exc)}

    # Sentry
    sentry_dsn = _os.getenv("SENTRY_DSN")
    components["sentry"] = {
        "status": "healthy" if sentry_dsn else "disabled",
        "configured": bool(sentry_dsn),
    }

    # OpenTelemetry
    otel_endpoint = _os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    components["otel"] = {
        "status": "healthy" if otel_endpoint else "disabled",
        "configured": bool(otel_endpoint),
    }

    return components


@app.get("/healthz")
async def healthz() -> dict:
    """Lightweight liveness probe (no I/O) for load balancers / Fly.io checks."""
    return {"status": "ok", "version": _APP_VERSION}


@app.get("/health")
async def health_check() -> dict:
    """Enhanced health check with uptime, memory, version, and component status."""
    uptime_seconds = round(_time.monotonic() - _APP_START_TIME, 2)
    components = _component_status()
    components["database"] = await _check_database()

    # Overall status: unhealthy if any required component is unhealthy
    required = {"billing", "auth", "database"}
    overall = "healthy"
    for name, info in components.items():
        if name in required and info.get("status") == "unhealthy":
            overall = "unhealthy"
            break

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": _APP_VERSION,
        "uptime_seconds": uptime_seconds,
        "python_version": sys.version.split()[0],
        "memory_mb": _memory_usage_mb(),
        "components": components,
    }


app.add_middleware(RequestLoggerMiddleware)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.gateway:app",
        host="0.0.0.0",
        port=int(_os.environ.get("GATEWAY_PORT", "8000")),
        reload=True,
    )
