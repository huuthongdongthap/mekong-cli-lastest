"""Regression tests for MEKONG_RAAS_DB env var support.

conftest.py sets MEKONG_RAAS_DB before any src.* imports so no test
touches ~/.mekong/raas/tenants.db.  The billing_db session fixture then
relocates the module constants to a per-run tmp DB.
"""
from __future__ import annotations

import os
from pathlib import Path

import src.raas.credits as credits_mod
import src.raas.mission_store as mission_mod
import src.raas.tenant as tenant_mod

_PROD = Path.home() / ".mekong" / "raas" / "tenants.db"


def test_env_var_is_set():
    """conftest must set MEKONG_RAAS_DB before any src import."""
    assert "MEKONG_RAAS_DB" in os.environ


def test_tenant_db_path_not_production():
    """_DB_PATH must never resolve to ~/.mekong/raas/tenants.db under test."""
    assert tenant_mod._DB_PATH != _PROD


def test_credit_db_path_not_production():
    assert credits_mod.DB_PATH != _PROD


def test_mission_db_path_not_production():
    assert mission_mod._DB_PATH != _PROD


def test_mission_db_path_matches_env_var():
    """mission_store._DB_PATH follows MEKONG_RAAS_DB (no session fixture overwrites it)."""
    expected = Path(os.environ["MEKONG_RAAS_DB"])
    assert mission_mod._DB_PATH == expected
