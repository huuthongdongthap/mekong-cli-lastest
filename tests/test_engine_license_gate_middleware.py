"""Unit and integration tests for EngineLicenseGateMiddleware."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from starlette.middleware.base import BaseHTTPMiddleware
from engine.billing.tier_config import Tier
import engine.license.license_gate_middleware as _lgm
from engine.license.license_gate_middleware import EngineLicenseGateMiddleware


@pytest.fixture(autouse=True)
def unmock_engine_license_gate(monkeypatch):
    """Restore real BaseHTTPMiddleware.__call__ since conftest patches it with passthrough."""
    monkeypatch.setattr(_lgm.EngineLicenseGateMiddleware, "__call__", BaseHTTPMiddleware.__call__)


@pytest.fixture
def isolate_license_store(tmp_path, monkeypatch):
    store_path = tmp_path / "licenses.json"
    monkeypatch.setenv("LICENSE_STORE_PATH", str(store_path))
    import engine.license.license_store as ls_mod

    ls_mod._default_store = None
    yield store_path
    ls_mod._default_store = None


def _seed_license(path: Path, license_key: str, customer_id: str, tier: str, status: str = "active") -> None:
    data = {}
    if path.exists():
        data = json.loads(path.read_text())
    data[license_key] = {
        "subscription_id": f"sub_{customer_id}",
        "customer_id": customer_id,
        "customer_email": f"{customer_id}@example.com",
        "tier": tier,
        "product_name": tier.capitalize(),
        "created_at": "2026-04-27T00:00:00+00:00",
        "status": status,
    }
    path.write_text(json.dumps(data))


class TestEngineLicenseGateMiddleware:
    def test_exempt_paths_bypass_gate(self, isolate_license_store):
        app = FastAPI()
        app.add_middleware(EngineLicenseGateMiddleware, minimum_tier=Tier.ENTERPRISE)

        @app.get("/health")
        def health():
            return {"status": "ok"}

        @app.get("/api-docs")
        def docs():
            return {"docs": "ok"}

        client = TestClient(app)
        res_health = client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json() == {"status": "ok"}

        res_docs = client.get("/api-docs")
        assert res_docs.status_code == 200

    def test_insufficient_tier_returns_402(self, isolate_license_store):
        app = FastAPI()
        app.add_middleware(EngineLicenseGateMiddleware, minimum_tier=Tier.PRO)

        @app.get("/data")
        def data():
            return {"message": "success"}

        client = TestClient(app)
        # Without user header -> current tier defaults to FREE < PRO
        resp = client.get("/data")
        assert resp.status_code == 402
        body = resp.json()
        assert body["error"] == "tier_required"
        assert body["required"] == "pro"
        assert body["current"] == "free"
        assert "upgrade_url" in body

    def test_sufficient_tier_passes_through(self, isolate_license_store):
        _seed_license(isolate_license_store, "lic_pro1", "user_pro", "pro")
        app = FastAPI()
        app.add_middleware(EngineLicenseGateMiddleware, minimum_tier=Tier.PRO)

        @app.get("/data")
        def data():
            return {"message": "success"}

        client = TestClient(app)
        resp = client.get("/data", headers={"X-User-Id": "user_pro"})
        assert resp.status_code == 200
        assert resp.json() == {"message": "success"}

    def test_query_param_user_id_accepted(self, isolate_license_store):
        _seed_license(isolate_license_store, "lic_ent1", "user_ent", "enterprise")
        app = FastAPI()
        app.add_middleware(EngineLicenseGateMiddleware, minimum_tier=Tier.ENTERPRISE)

        @app.get("/export")
        def export():
            return {"exported": True}

        client = TestClient(app)
        resp = client.get("/export?user_id=user_ent")
        assert resp.status_code == 200
        assert resp.json() == {"exported": True}

    def test_tier_from_env_var(self, isolate_license_store, monkeypatch):
        monkeypatch.setenv("MEKONG_MINIMUM_TIER", "GROWTH")
        app = FastAPI()
        app.add_middleware(EngineLicenseGateMiddleware)

        @app.get("/action")
        def action():
            return {"ok": True}

        client = TestClient(app)
        # FREE < GROWTH -> 402
        res_fail = client.get("/action")
        assert res_fail.status_code == 402
        assert res_fail.json()["required"] == "growth"

        # Seed growth user -> 200
        _seed_license(isolate_license_store, "lic_grow", "user_grow", "growth")
        res_pass = client.get("/action", headers={"X-User-Id": "user_grow"})
        assert res_pass.status_code == 200

    def test_invalid_env_tier_falls_back_to_free(self, monkeypatch):
        monkeypatch.setenv("MEKONG_MINIMUM_TIER", "NON_EXISTENT_TIER")
        tier = EngineLicenseGateMiddleware._tier_from_env()
        assert tier == Tier.FREE
