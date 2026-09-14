"""Unit and integration tests for Tier Config API Routes mounted on gateway."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from src.gateway import app


@pytest.fixture
def client():
    return TestClient(app)


def _collect_tier_config_deps():
    """Collect the exact _RoleDependency instances registered on /api/tier-configs routes."""
    deps = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/tier-configs"):
            for dep in getattr(getattr(route, "dependant", None), "dependencies", []):
                deps[dep.call] = dep.call
    return deps


def _make_mock_repo(all_configs: dict | None = None, per_tier_config=None):
    """Build an async-capable mock TierConfigRepository.

    all_configs: mapping tier -> preset -> TierConfig-like object.
                 When None, get_all_configs returns {}.
    per_tier_config: callable(tier, preset) -> TierConfig or None.
                     When None, get_config always returns None.
    """
    repo = MagicMock()
    repo.get_all_configs = AsyncMock(return_value=all_configs or {})

    async def _get_config(tier, preset):
        if per_tier_config is not None:
            return per_tier_config(tier, preset)
        return None

    repo.get_config = _get_config
    return repo


class TestTierConfigRoutesAuth:
    """Test authentication and RBAC enforcement on tier-config routes."""

    def test_list_tier_configs_unauthenticated_returns_401(self, client):
        resp = client.get("/api/tier-configs")
        assert resp.status_code == 401

    def test_get_tier_config_unauthenticated_returns_401(self, client):
        resp = client.get("/api/tier-configs/pro")
        assert resp.status_code == 401


class TestTierConfigRoutesAuthorized:
    """Test authorized access to tier config endpoints.

    All _RoleDependency callables are bypassed via dependency_overrides.
    The DB repository is mocked to avoid a live database connection.
    """

    @pytest.fixture(autouse=True)
    def override_admin_role(self):
        # Override the exact _RoleDependency instances registered on the live
        # /api/tier-configs routes.  require_role() returns a fresh object each
        # time it is called, so we must walk the mounted route graph.
        deps = _collect_tier_config_deps()
        for call in deps:
            app.dependency_overrides[call] = lambda: None
        yield
        for call in deps:
            app.dependency_overrides.pop(call, None)

    def test_list_tier_configs_returns_all_tiers(self, client):
        # Provide a fake DB result covering every canonical tier + the two
        # presets the test asserts on.
        from src.db.tier_config_repository import TierConfig

        def _make(tier, preset, rate_limit=100):
            return TierConfig(id=None, tier=tier, preset=preset,
                              rate_limit=rate_limit, window_seconds=60)

        fake_configs = {}
        for tier in ["free", "trial", "starter", "pro", "enterprise"]:
            fake_configs[tier] = {
                "auth_login": _make(tier, "auth_login"),
                "auth_callback": _make(tier, "auth_callback"),
                "auth_refresh": _make(tier, "auth_refresh"),
                "api_default": _make(tier, "api_default", rate_limit=200),
            }

        mock_repo = _make_mock_repo(all_configs=fake_configs)

        with patch("src.db.tier_config_repository.get_repository", return_value=mock_repo):
            resp = client.get("/api/tier-configs")

        assert resp.status_code == 200
        data = resp.json()
        assert "configs" in data
        configs = data["configs"]
        for tier in ["free", "trial", "starter", "pro", "enterprise"]:
            assert tier in configs, f"tier '{tier}' missing from response"
            assert "auth_login" in configs[tier]
            assert "api_default" in configs[tier]

    def test_get_tier_config_valid_tier(self, client):
        # DB returns nothing → route falls back to engine canonical defaults.
        mock_repo = _make_mock_repo()  # get_config always returns None

        with patch("src.db.tier_config_repository.get_repository", return_value=mock_repo):
            resp = client.get("/api/tier-configs/pro")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        presets = {item["preset"]: item for item in data}
        assert "auth_login" in presets
        assert "api_default" in presets
        assert presets["api_default"]["rate_limit"] > 0

    def test_get_tier_config_invalid_tier_returns_404(self, client):
        # DB returns nothing → route tries engine fallback → ValueError → 404.
        mock_repo = _make_mock_repo()

        with patch("src.db.tier_config_repository.get_repository", return_value=mock_repo):
            resp = client.get("/api/tier-configs/invalid_nonexistent_tier")

        assert resp.status_code == 404
