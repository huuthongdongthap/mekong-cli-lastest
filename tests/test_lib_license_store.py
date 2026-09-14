"""Tests for engine.license.license_store."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.license import license_store as ls_mod
from engine.license.license_store import LicenseStore, get_license_store


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    ls_mod._default_store = None
    yield
    ls_mod._default_store = None


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


class TestEmptyStore:
    def test_get_returns_none(self, tmp_path):
        store = LicenseStore(path=tmp_path / "missing.json")
        assert store.get("any") is None
        assert store.is_active("any") is False
        assert store.tenant_id("any") is None
        assert store.tier("any") is None

    def test_corrupt_file_treated_as_empty(self, tmp_path):
        path = tmp_path / "licenses.json"
        path.write_text("not-json")
        store = LicenseStore(path=path)
        assert store.get("anything") is None


class TestActiveLookup:
    def test_active_license(self, tmp_path):
        path = tmp_path / "licenses.json"
        _write(
            path,
            {
                "lic_a": {
                    "customer_id": "cus_1",
                    "tier": "starter",
                    "status": "active",
                }
            },
        )
        store = LicenseStore(path=path)
        assert store.is_active("lic_a") is True
        assert store.tenant_id("lic_a") == "cus_1"
        assert store.tier("lic_a") == "starter"

    def test_cancelled_license(self, tmp_path):
        path = tmp_path / "licenses.json"
        _write(
            path,
            {"lic_c": {"customer_id": "cus_2", "tier": "pro", "status": "cancelled"}},
        )
        store = LicenseStore(path=path)
        assert store.is_active("lic_c") is False

    def test_root_array_treated_as_empty(self, tmp_path):
        path = tmp_path / "licenses.json"
        path.write_text(json.dumps(["not", "a", "dict"]))
        store = LicenseStore(path=path)
        assert store.get("any") is None


class TestSingleton:
    def test_get_license_store_returns_singleton(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LICENSE_STORE_PATH", str(tmp_path / "x.json"))
        a = get_license_store()
        b = get_license_store()
        assert a is b

    def test_env_override_path(self, monkeypatch, tmp_path):
        target = tmp_path / "custom.json"
        monkeypatch.setenv("LICENSE_STORE_PATH", str(target))
        store = get_license_store()
        assert store.path == target


class TestGetActiveLicense:
    def test_lookup_by_various_identifiers(self, tmp_path):
        path = tmp_path / "licenses.json"
        _write(
            path,
            {
                "lic_prod_1": {
                    "subscription_id": "sub_999",
                    "customer_id": "cus_tenant_1",
                    "customer_email": "founder@mekong.ai",
                    "tier": "enterprise",
                    "product_name": "Enterprise Suite",
                    "created_at": "2026-04-27T00:00:00+00:00",
                    "status": "active",
                },
                "lic_inactive": {
                    "subscription_id": "sub_000",
                    "customer_id": "cus_inactive",
                    "customer_email": "inactive@mekong.ai",
                    "tier": "pro",
                    "product_name": "Pro Suite",
                    "created_at": "2026-04-27T00:00:00+00:00",
                    "status": "cancelled",
                },
            },
        )
        store = LicenseStore(path=path)

        # 1. Direct license_key match
        lic1 = store.get_active_license("lic_prod_1")
        assert lic1 is not None
        assert lic1.license_key == "lic_prod_1"
        assert lic1.tier == "enterprise"
        assert lic1["tier"] == "enterprise"
        assert lic1.get("customer_id") == "cus_tenant_1"
        assert lic1.customer_email == "founder@mekong.ai"
        assert lic1.subscription_id == "sub_999"

        # 2. Customer ID match
        lic2 = store.get_active_license("cus_tenant_1")
        assert lic2 is not None
        assert lic2.license_key == "lic_prod_1"
        assert lic2.tier == "enterprise"

        # 3. Customer email match
        lic3 = store.get_active_license("founder@mekong.ai")
        assert lic3 is not None
        assert lic3.license_key == "lic_prod_1"

        # 4. Subscription ID match
        lic4 = store.get_active_license("sub_999")
        assert lic4 is not None
        assert lic4.license_key == "lic_prod_1"

        # 5. Inactive license returns None
        assert store.get_active_license("lic_inactive") is None
        assert store.get_active_license("cus_inactive") is None
        assert store.get_active_license("inactive@mekong.ai") is None

        # 6. Nonexistent user returns None
        assert store.get_active_license("nonexistent_user") is None

        # 7. user_id=None without env returns None
        assert store.get_active_license(None) is None

    def test_lookup_via_env_var_when_user_id_none(self, tmp_path, monkeypatch):
        path = tmp_path / "licenses.json"
        _write(
            path,
            {
                "lic_env_1": {
                    "customer_id": "cus_env",
                    "tier": "growth",
                    "status": "active",
                }
            },
        )
        store = LicenseStore(path=path)

        monkeypatch.setenv("MEKONG_LICENSE_KEY", "lic_env_1")
        lic = store.get_active_license(None)
        assert lic is not None
        assert lic.tier == "growth"

        monkeypatch.delenv("MEKONG_LICENSE_KEY", raising=False)
        monkeypatch.setenv("MEKONG_USER_ID", "cus_env")
        lic2 = store.get_active_license(None)
        assert lic2 is not None
        assert lic2.tier == "growth"

