"""Tests for src.api.auth_routes (POST /auth/login)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth_routes import (
    JWT_ALGORITHM,
    REFRESH_TOKEN_TTL_SECONDS,
    router,
)
from src.auth.rate_limiter import RateLimitPreset
from src.middleware.rate_limit_gateway_middleware import _resolve_preset


@pytest.fixture(autouse=True)
def _isolate_license_store(tmp_path, monkeypatch):
    store_path = tmp_path / "licenses.json"
    monkeypatch.setenv("LICENSE_STORE_PATH", str(store_path))
    from engine.license import license_store as ls_mod

    ls_mod._default_store = None
    yield store_path
    ls_mod._default_store = None


@pytest.fixture
def jwt_secret(monkeypatch) -> str:
    secret = "auth-test-secret"
    monkeypatch.setenv("JWT_SECRET", secret)
    return secret


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed(path: Path, key: str, **overrides) -> None:
    record = {
        "subscription_id": "sub_1",
        "customer_id": "cus_99",
        "customer_email": "u@example.com",
        "tier": "growth",
        "product_name": "Growth",
        "created_at": "2026-04-27T00:00:00+00:00",
        "status": "active",
    }
    record.update(overrides)
    path.write_text(json.dumps({key: record}))


class TestLoginEndpoint:
    def test_invalid_license_returns_401(self, client):
        resp = client.post("/auth/login", json={"license_key": "lic_does_not_exist"})
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "invalid_license"

    def test_inactive_license_returns_402(
        self, client, _isolate_license_store
    ):
        _seed(_isolate_license_store, "lic_inactive", status="cancelled")
        resp = client.post("/auth/login", json={"license_key": "lic_inactive"})
        assert resp.status_code == 402
        assert resp.json()["detail"]["error"] == "license_inactive"

    def test_success_returns_jwt(self, client, _isolate_license_store, jwt_secret):
        _seed(_isolate_license_store, "lic_okay99")
        resp = client.post("/auth/login", json={"license_key": "lic_okay99"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == "cus_99"
        assert body["tier"] == "growth"
        assert body["expires_in"] == 3600
        assert body["token_type"] == "Bearer"

        claims = jwt.decode(
            body["access_token"], jwt_secret, algorithms=[JWT_ALGORITHM]
        )
        assert claims["tenant_id"] == "cus_99"
        assert claims["license_key"] == "lic_okay99"
        assert claims["tier"] == "growth"
        assert claims["exp"] - claims["iat"] == 3600

    def test_missing_tenant_id_returns_500(
        self, client, _isolate_license_store
    ):
        _seed(_isolate_license_store, "lic_broken", customer_id=None)
        resp = client.post("/auth/login", json={"license_key": "lic_broken"})
        assert resp.status_code == 500
        assert resp.json()["detail"]["error"] == "license_missing_tenant"

    def test_validation_rejects_short_key(self, client):
        resp = client.post("/auth/login", json={"license_key": "x"})
        assert resp.status_code == 422  # pydantic validation

    def test_token_iat_recent(self, client, _isolate_license_store, jwt_secret):
        _seed(_isolate_license_store, "lic_nowkey")
        before = int(time.time())
        resp = client.post("/auth/login", json={"license_key": "lic_nowkey"})
        after = int(time.time())
        assert resp.status_code == 200
        claims = jwt.decode(
            resp.json()["access_token"], jwt_secret, algorithms=[JWT_ALGORITHM]
        )
        assert before <= claims["iat"] <= after


class TestRefreshEndpoint:
    def test_refresh_success(self, client, _isolate_license_store, jwt_secret):
        _seed(_isolate_license_store, "lic_refresh99", tier="growth")
        login_resp = client.post("/auth/login", json={"license_key": "lic_refresh99"})
        assert login_resp.status_code == 200
        login_body = login_resp.json()
        assert "refresh_token" in login_body
        refresh_token = login_body["refresh_token"]

        resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == "cus_99"
        assert body["tier"] == "growth"
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == 3600
        assert "access_token" in body
        assert "refresh_token" in body

        access_claims = jwt.decode(
            body["access_token"], jwt_secret, algorithms=[JWT_ALGORITHM]
        )
        assert access_claims["tenant_id"] == "cus_99"
        assert access_claims["license_key"] == "lic_refresh99"
        assert access_claims["tier"] == "growth"
        assert access_claims["token_type"] == "access"
        assert access_claims["exp"] - access_claims["iat"] == 3600

        refresh_claims = jwt.decode(
            body["refresh_token"], jwt_secret, algorithms=[JWT_ALGORITHM]
        )
        assert refresh_claims["tenant_id"] == "cus_99"
        assert refresh_claims["license_key"] == "lic_refresh99"
        assert refresh_claims["tier"] == "growth"
        assert refresh_claims["token_type"] == "refresh"
        assert refresh_claims["exp"] - refresh_claims["iat"] == REFRESH_TOKEN_TTL_SECONDS

    def test_refresh_dynamic_tier_upgrade(
        self, client, _isolate_license_store, jwt_secret
    ):
        _seed(_isolate_license_store, "lic_upgrade", tier="starter")
        login_resp = client.post("/auth/login", json={"license_key": "lic_upgrade"})
        assert login_resp.status_code == 200
        refresh_token = login_resp.json()["refresh_token"]

        # Upgrade tier in license store
        _seed(_isolate_license_store, "lic_upgrade", tier="enterprise")

        resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["tier"] == "enterprise"

        access_claims = jwt.decode(
            body["access_token"], jwt_secret, algorithms=[JWT_ALGORITHM]
        )
        assert access_claims["tier"] == "enterprise"

    def test_refresh_invalid_token_returns_401(self, client):
        resp = client.post("/auth/refresh", json={"refresh_token": "invalid.jwt.token"})
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "invalid_token"

    def test_refresh_expired_token_returns_401(
        self, client, _isolate_license_store, jwt_secret
    ):
        now = int(time.time())
        expired_payload = {
            "tenant_id": "cus_99",
            "license_key": "lic_exp",
            "tier": "starter",
            "token_type": "refresh",
            "iat": now - 7200,
            "exp": now - 3600,
        }
        expired_token = jwt.encode(expired_payload, jwt_secret, algorithm=JWT_ALGORITHM)
        resp = client.post("/auth/refresh", json={"refresh_token": expired_token})
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "token_expired"

    def test_refresh_with_access_token_rejected(
        self, client, _isolate_license_store
    ):
        _seed(_isolate_license_store, "lic_acc_reject")
        login_resp = client.post("/auth/login", json={"license_key": "lic_acc_reject"})
        access_token = login_resp.json()["access_token"]

        resp = client.post("/auth/refresh", json={"refresh_token": access_token})
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "invalid_token_type"

    def test_refresh_malformed_claims_returns_401(
        self, client, _isolate_license_store, jwt_secret
    ):
        now = int(time.time())
        # Missing license_key
        payload = {
            "tenant_id": "cus_99",
            "token_type": "refresh",
            "iat": now,
            "exp": now + 3600,
        }
        token = jwt.encode(payload, jwt_secret, algorithm=JWT_ALGORITHM)
        resp = client.post("/auth/refresh", json={"refresh_token": token})
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "malformed_claims"

    def test_refresh_unknown_license_returns_401(
        self, client, _isolate_license_store, jwt_secret
    ):
        now = int(time.time())
        payload = {
            "tenant_id": "cus_99",
            "license_key": "lic_nonexistent_key",
            "token_type": "refresh",
            "iat": now,
            "exp": now + 3600,
        }
        token = jwt.encode(payload, jwt_secret, algorithm=JWT_ALGORITHM)
        resp = client.post("/auth/refresh", json={"refresh_token": token})
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "invalid_license"

    def test_refresh_inactive_license_returns_402(
        self, client, _isolate_license_store
    ):
        _seed(_isolate_license_store, "lic_active_cancel", status="active")
        login_resp = client.post(
            "/auth/login", json={"license_key": "lic_active_cancel"}
        )
        refresh_token = login_resp.json()["refresh_token"]

        # Cancel license
        _seed(_isolate_license_store, "lic_active_cancel", status="cancelled")

        resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 402
        assert resp.json()["detail"]["error"] == "license_inactive"

    def test_rate_limit_preset_resolution(self):
        assert _resolve_preset("POST", "/auth/refresh") == RateLimitPreset.AUTH_REFRESH
        assert (
            _resolve_preset("POST", "/v1/auth/refresh") == RateLimitPreset.AUTH_REFRESH
        )
        assert _resolve_preset("POST", "/auth/login") == RateLimitPreset.AUTH_LOGIN
        assert (
            _resolve_preset("POST", "/v1/auth/magic-link")
            == RateLimitPreset.AUTH_LOGIN
        )
        assert _resolve_preset("POST", "/api/data") == RateLimitPreset.API_WRITE
        assert _resolve_preset("GET", "/api/data") == RateLimitPreset.API_READ
