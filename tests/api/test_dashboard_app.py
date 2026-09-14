"""
Unit tests for src/api/dashboard/app.py

The dashboard package __init__.py re-exports `app` directly, so
`import src.api.dashboard.app` resolves to the FastAPI instance.
We load the module via importlib to get the actual module namespace.

All external dependencies (DashboardService, AuthConfig, SessionMiddleware,
StaticFiles) are patched to avoid DB/filesystem/network calls.
"""

import os
import sys
import importlib
import importlib.util
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("AUTH_ENVIRONMENT", "dev")
os.environ.setdefault("TESTING", "true")


# ---------------------------------------------------------------------------
# Patch infrastructure BEFORE the app module is loaded
# ---------------------------------------------------------------------------

patch("fastapi.staticfiles.StaticFiles.__init__", lambda self, *a, **kw: None).start()
patch("fastapi.FastAPI.mount", lambda self, *a, **kw: None).start()
patch("src.auth.middleware.SessionManager", MagicMock).start()
patch("src.auth.middleware.UserRepository", MagicMock).start()
_rl = MagicMock()
_rl.check_limit = AsyncMock(return_value=(True, {}))
patch("src.auth.middleware.get_rate_limiter", lambda: _rl).start()

# ── Auth decorator: mock BEFORE app module loads ──────────────────────────────
# FastAPI captures require_permission at route-registration time.
# Patching here ensures the passthrough is baked in before @app.get(...) runs.
_passthrough = MagicMock(side_effect=lambda *a, **kw: lambda f: f)
_p_perm = patch("src.auth.rbac.require_permission", _passthrough)
_p_perm.start()
_p_user = patch("src.auth.rbac.get_current_user", MagicMock(return_value=None))
_p_user.start()


def _load_app_module():
    """Load src/api/dashboard/app.py as a real module object (not the re-exported FastAPI instance)."""
    app_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "src", "api", "dashboard", "app.py"
    )
    app_path = os.path.abspath(app_path)
    module_name = "src.api.dashboard.app"

    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, app_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_app_mod = _load_app_module()
_p_perm.stop()
_p_user.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metrics(**overrides):
    defaults = dict(
        api_calls={"total": 100},
        active_licenses=[{"license_key": "raas-pro-abc", "tier": "pro", "email": "a@b.com", "key_id": "abc"}],
        top_endpoints=[{"endpoint": "/v1/check", "calls": 50}],
        revenue={"total_mrr": 500.0},
        tier_distribution={"pro": 1},
        last_updated="2026-04-04T00:00:00Z",
        license_health={"active": 1, "expired": 0},
        renewal_prompts=[{"license_key": "x", "days_since_or_until_expiry": 3}],
        rate_limit_events=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_dashboard_service(metric):
    svc = MagicMock()
    svc.get_metrics = AsyncMock(return_value=metric)

    queries = MagicMock()
    queries.get_daily_usage = AsyncMock(return_value=[{"date": "2026-01-01", "calls": 10}])
    queries.get_active_licenses = AsyncMock(return_value=metric.active_licenses)
    queries.get_top_endpoints = AsyncMock(return_value=metric.top_endpoints)
    svc._queries = queries
    svc._format_chart_data = MagicMock(return_value={"labels": [], "values": []})
    svc.export_to_csv = AsyncMock(return_value="col1,col2\nval1,val2")
    svc.export_to_json = AsyncMock(return_value='{"data": []}')

    emitter = MagicMock()
    emitter.get_recent_events = AsyncMock(return_value=[])
    svc._rate_limit_emitter = emitter
    return svc


def _make_auth_config():
    cfg = MagicMock()
    cfg.get_config_summary.return_value = {"environment": "dev", "auth_enabled": False}
    return cfg


def _make_fake_templates():
    from fastapi.responses import HTMLResponse
    tpl = MagicMock()
    tpl.TemplateResponse = MagicMock(
        side_effect=lambda name, ctx, **kw: HTMLResponse("<html>dashboard</html>")
    )
    return tpl


def _passthrough_decorator(permission):
    def decorator(func):
        return func
    return decorator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_service():
    """Replace module-level singleton + decorators for each test."""
    fake_metric = _make_metrics()
    svc = _make_dashboard_service(fake_metric)

    _app_mod.dashboard_service = svc
    orig_templates = _app_mod.templates
    _app_mod.templates = _make_fake_templates()
    orig_auth = _app_mod.AuthConfig
    _app_mod.AuthConfig = lambda: _make_auth_config()

    yield fake_metric, svc

    _app_mod.dashboard_service = svc  # keep mock between tests in same session
    _app_mod.templates = orig_templates
    _app_mod.AuthConfig = orig_auth


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    return TestClient(_app_mod.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_healthy(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_auth_summary_included(self, client):
        assert "auth" in client.get("/health").json()


# ---------------------------------------------------------------------------
# /api/metrics
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    def test_returns_success_true(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_contains_expected_keys(self, client):
        data = client.get("/api/metrics").json()["data"]
        for key in ("api_calls", "active_licenses", "top_endpoints", "revenue",
                    "tier_distribution", "last_updated", "license_health",
                    "renewal_prompts", "rate_limit_events"):
            assert key in data

    def test_range_days_query_param_accepted(self, client):
        assert client.get("/api/metrics?range_days=7").status_code == 200

    def test_invalid_range_days_returns_422(self, client):
        assert client.get("/api/metrics?range_days=0").status_code == 422

    def test_service_exception_returns_500(self, client, _patch_service):
        _, svc = _patch_service
        svc.get_metrics = AsyncMock(side_effect=RuntimeError("db down"))
        assert client.get("/api/metrics").status_code == 500


# ---------------------------------------------------------------------------
# /api/metrics/api-calls
# ---------------------------------------------------------------------------

class TestApiCallsEndpoint:
    def test_happy_path(self, client):
        resp = client.get("/api/metrics/api-calls?start_date=2026-01-01&end_date=2026-01-31")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_missing_start_date_returns_422(self, client):
        assert client.get("/api/metrics/api-calls?end_date=2026-01-31").status_code == 422

    def test_bad_date_format_returns_422(self, client):
        assert client.get(
            "/api/metrics/api-calls?start_date=01-01-2026&end_date=2026-01-31"
        ).status_code == 422

    def test_granularity_week(self, client):
        assert client.get(
            "/api/metrics/api-calls?start_date=2026-01-01&end_date=2026-01-31&granularity=week"
        ).status_code == 200


# ---------------------------------------------------------------------------
# /api/metrics/licenses
# ---------------------------------------------------------------------------

class TestLicensesEndpoint:
    def test_returns_active_licenses(self, client):
        resp = client.get("/api/metrics/licenses")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert isinstance(resp.json()["data"], list)

    def test_date_param_accepted(self, client):
        assert client.get("/api/metrics/licenses?date=2026-04-01").status_code == 200


# ---------------------------------------------------------------------------
# /api/endpoints
# ---------------------------------------------------------------------------

class TestEndpointsEndpoint:
    def test_happy_path(self, client):
        resp = client.get("/api/endpoints")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_limit_param(self, client):
        assert client.get("/api/endpoints?limit=5").status_code == 200

    def test_limit_too_large_returns_422(self, client):
        assert client.get("/api/endpoints?limit=100").status_code == 422


# ---------------------------------------------------------------------------
# /api/export
# ---------------------------------------------------------------------------

class TestExportEndpoint:
    def test_json_export(self, client):
        resp = client.get("/api/export?format=json")
        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]

    def test_csv_export(self, client):
        resp = client.get("/api/export?format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]

    def test_with_explicit_date_range(self, client):
        assert client.get("/api/export?start=2026-01-01&end=2026-01-31").status_code == 200

    def test_invalid_format_returns_422(self, client):
        assert client.get("/api/export?format=xlsx").status_code == 422

    def test_export_error_returns_500(self, client, _patch_service):
        _, svc = _patch_service
        svc.export_to_json = AsyncMock(side_effect=RuntimeError("fail"))
        assert client.get("/api/export?format=json").status_code == 500


# ---------------------------------------------------------------------------
# /api/license-health
# ---------------------------------------------------------------------------

class TestLicenseHealthEndpoint:
    def test_returns_health_data(self, client):
        resp = client.get("/api/license-health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "active" in data["data"]

    def test_service_error_returns_500(self, client, _patch_service):
        _, svc = _patch_service
        svc.get_metrics = AsyncMock(side_effect=Exception("boom"))
        assert client.get("/api/license-health").status_code == 500


# ---------------------------------------------------------------------------
# /api/renewal-prompts
# ---------------------------------------------------------------------------

class TestRenewalPromptsEndpoint:
    def test_happy_path(self, client):
        resp = client.get("/api/renewal-prompts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "window_days" in data["metadata"]

    def test_days_param_filters_prompts(self, client, _patch_service):
        _, svc = _patch_service
        metric = _make_metrics(
            renewal_prompts=[
                {"days_since_or_until_expiry": 2},
                {"days_since_or_until_expiry": 10},
            ]
        )
        svc.get_metrics = AsyncMock(return_value=metric)

        resp = client.get("/api/renewal-prompts?days=3")
        assert resp.status_code == 200
        assert resp.json()["metadata"]["total_count"] == 1

    def test_days_out_of_range_returns_422(self, client):
        assert client.get("/api/renewal-prompts?days=0").status_code == 422


# ---------------------------------------------------------------------------
# /api/rate-limit-events
# ---------------------------------------------------------------------------

class TestRateLimitEventsEndpoint:
    def test_returns_events(self, client):
        resp = client.get("/api/rate-limit-events")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert isinstance(resp.json()["data"], list)

    def test_optional_filters_accepted(self, client):
        resp = client.get("/api/rate-limit-events?event_type=blocked&tenant_id=t1")
        assert resp.status_code == 200

    def test_limit_out_of_range_returns_422(self, client):
        assert client.get("/api/rate-limit-events?limit=201").status_code == 422


# ---------------------------------------------------------------------------
# /api/filters/licenses
# ---------------------------------------------------------------------------

class TestLicenseFiltersEndpoint:
    def test_returns_deduplicated_keys(self, client, _patch_service):
        _, svc = _patch_service
        licenses = [
            {"license_key": "key123", "key_id": "k1", "tier": "pro", "email": "a@b.com"},
            {"license_key": "key123", "key_id": "k1", "tier": "pro", "email": "a@b.com"},  # dup
            {"license_key": "key456", "key_id": "k2", "tier": "free", "email": "c@d.com"},
        ]
        svc._queries.get_active_licenses = AsyncMock(return_value=licenses)

        resp = client.get("/api/filters/licenses")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_long_license_key_truncated(self, client, _patch_service):
        _, svc = _patch_service
        long_key = "a" * 30
        svc._queries.get_active_licenses = AsyncMock(return_value=[
            {"license_key": long_key, "key_id": "k1", "tier": "pro", "email": "a@b.com"}
        ])

        result_key = client.get("/api/filters/licenses").json()["data"][0]["license_key"]
        assert result_key.endswith("...")


# ---------------------------------------------------------------------------
# /api/telemetry/* — DB-dependent, test routing/validation only
# ---------------------------------------------------------------------------

class TestTelemetryEventsEndpoint:
    def test_limit_exceeds_max_returns_422(self, client):
        assert client.get("/api/telemetry/events?limit=9999").status_code == 422

    def test_valid_limit_accepted(self, client):
        resp = client.get("/api/telemetry/events?limit=50")
        assert resp.status_code in (200, 500)

    def test_endpoint_exists(self, client):
        assert client.get("/api/telemetry/events").status_code in (200, 500)


class TestCliVersionsEndpoint:
    def test_endpoint_exists(self, client):
        assert client.get("/api/telemetry/cli-versions").status_code in (200, 500)


class TestSessionStatsEndpoint:
    def test_endpoint_exists(self, client):
        assert client.get("/api/telemetry/sessions").status_code in (200, 500)

    def test_range_days_param(self, client):
        assert client.get("/api/telemetry/sessions?range_days=7").status_code in (200, 500)
