"""Unit tests for src/core/gateway/gateway_main.py.

Tests cover:
- verify_token: valid, missing env, invalid token
- build_human_summary: all three status branches
- _scan_projects: dir scanning logic
- _build_cmd_response: response assembly
- create_app: FastAPI routes via TestClient
"""

import os
from dataclasses import dataclass, field
from enum import Enum
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Minimal stubs for heavy transitive imports
# ---------------------------------------------------------------------------

class _FakeStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class _FakeRecipe:
    name: str = "test-recipe"
    steps: list = field(default_factory=list)


@dataclass
class _FakeOrchResult:
    status: _FakeStatus = _FakeStatus.SUCCESS
    recipe: _FakeRecipe = field(default_factory=_FakeRecipe)
    step_results: list = field(default_factory=list)
    total_steps: int = 3
    completed_steps: int = 3
    failed_steps: int = 0
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100


# ---------------------------------------------------------------------------
# Module-level patches applied before import so heavy deps don't execute
# ---------------------------------------------------------------------------

PATCH_BASE = "src.core.gateway.gateway_main"

_MODULE_PATCHES = {
    "src.core.event_bus.get_event_bus": MagicMock(),
    "src.core.event_bus.EventType": MagicMock(),
    "src.core.gateway_config.load_config": MagicMock(return_value=MagicMock(
        presets=[
            {
                "id": "p1", "label": "Deploy", "label_vi": "Deploy VI",
                "description": "Deploy app", "goal": "deploy", "icon": "rocket", "color": "blue",
            }
        ],
        project_paths=[],
    )),
    "src.core.gateway_dashboard.DASHBOARD_HTML": "__PRESETS_JSON____VERSION__",
    "src.providers.llm.client.get_client": MagicMock(return_value=MagicMock(is_available=False)),
    "src.core.memory_canonical.MemoryStore": MagicMock(),
    "src.core.orchestrator.OrchestrationResult": _FakeOrchResult,
    "src.core.orchestrator.RecipeOrchestrator": MagicMock(),
    "src.core.scheduler.Scheduler": MagicMock(),
    "src.core.swarm.SwarmRegistry": MagicMock(),
    "src.api.raas_router.router": MagicMock(routes=[]),
    "src.api.tier_config_routes.router": MagicMock(routes=[]),
    "src.api.quota_status_endpoints.quota_router": MagicMock(routes=[]),
}


@pytest.fixture(scope="module", autouse=True)
def patch_heavy_imports():
    """Patch all external heavy dependencies at module level."""
    patchers = [patch(target, val) for target, val in _MODULE_PATCHES.items()]
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


@pytest.fixture(scope="module")
def gateway_module(patch_heavy_imports):
    """Import gateway_main after all patches are active."""
    import sys
    # Remove cached module if present so patches take effect
    for mod_name in list(sys.modules.keys()):
        if "gateway_main" in mod_name or "gateway_config" in mod_name:
            del sys.modules[mod_name]
    import src.core.gateway.gateway_main as gm
    return gm


# ===========================================================================
# verify_token tests
# ===========================================================================

class TestVerifyToken:
    def test_valid_token_passes(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "secret123"}):
            # Should not raise
            gateway_module.verify_token("secret123")

    def test_missing_env_raises_500(self, gateway_module):
        env = {k: v for k, v in os.environ.items() if k != "MEKONG_API_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(HTTPException) as exc_info:
                gateway_module.verify_token("anything")
            assert exc_info.value.status_code == 500

    def test_invalid_token_raises_401(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "correct"}):
            with pytest.raises(HTTPException) as exc_info:
                gateway_module.verify_token("wrong")
            assert exc_info.value.status_code == 401

    def test_empty_token_raises_401(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "correct"}):
            with pytest.raises(HTTPException) as exc_info:
                gateway_module.verify_token("")
            assert exc_info.value.status_code == 401


# ===========================================================================
# build_human_summary tests
# ===========================================================================

class TestBuildHumanSummary:
    def _make_result(self, status_val, completed=3, total=3, failed=0):
        result = MagicMock()
        result.status.value = status_val
        result.completed_steps = completed
        result.total_steps = total
        result.failed_steps = failed
        result.success_rate = (completed / total * 100) if total else 0.0
        return result

    def test_success_status(self, gateway_module):
        result = self._make_result("success", completed=5)
        summary = gateway_module.build_human_summary(result)
        assert "5" in summary.en
        assert summary.vi  # non-empty Vietnamese
        assert "done" in summary.en.lower() or "completed" in summary.en.lower()

    def test_partial_status(self, gateway_module):
        result = self._make_result("partial", completed=2, total=4, failed=2)
        summary = gateway_module.build_human_summary(result)
        assert "2/4" in summary.en or "2" in summary.en
        assert summary.vi

    def test_failed_status(self, gateway_module):
        result = self._make_result("failed", completed=0, total=3, failed=3)
        summary = gateway_module.build_human_summary(result)
        assert "3" in summary.en
        assert summary.vi
        assert "fail" in summary.en.lower() or "problem" in summary.en.lower()

    def test_human_summary_returns_correct_model(self, gateway_module):
        from src.core.gateway.models import HumanSummary
        result = self._make_result("success")
        summary = gateway_module.build_human_summary(result)
        assert isinstance(summary, HumanSummary)
        assert isinstance(summary.en, str)
        assert isinstance(summary.vi, str)


# ===========================================================================
# _scan_projects tests
# ===========================================================================

class TestScanProjects:
    def test_empty_project_paths(self, gateway_module):
        with patch.object(gateway_module.GATEWAY_CONFIG, "project_paths", []):
            result = gateway_module._scan_projects()
            assert result == []

    def test_nonexistent_base_dir_skipped(self, gateway_module, tmp_path):
        fake_path = str(tmp_path / "nonexistent")
        with patch.object(gateway_module.GATEWAY_CONFIG, "project_paths", [fake_path]):
            result = gateway_module._scan_projects()
            assert result == []

    def test_scans_subdirs(self, gateway_module, tmp_path):
        # Create a project layout
        (tmp_path / "app-one").mkdir()
        (tmp_path / "app-two").mkdir()
        (tmp_path / ".hidden").mkdir()  # should be skipped
        (tmp_path / "file.txt").write_text("ignored")

        with patch.object(gateway_module.GATEWAY_CONFIG, "project_paths", [str(tmp_path)]):
            result = gateway_module._scan_projects()

        names = [p.name for p in result]
        assert "app-one" in names
        assert "app-two" in names
        assert ".hidden" not in names

    def test_has_git_detection(self, gateway_module, tmp_path):
        proj = tmp_path / "my-project"
        proj.mkdir()
        (proj / ".git").mkdir()

        with patch.object(gateway_module.GATEWAY_CONFIG, "project_paths", [str(tmp_path)]):
            result = gateway_module._scan_projects()

        assert len(result) == 1
        assert result[0].has_git is True
        assert result[0].name == "my-project"

    def test_no_git_project(self, gateway_module, tmp_path):
        proj = tmp_path / "bare-project"
        proj.mkdir()

        with patch.object(gateway_module.GATEWAY_CONFIG, "project_paths", [str(tmp_path)]):
            result = gateway_module._scan_projects()

        assert result[0].has_git is False


# ===========================================================================
# _build_cmd_response tests
# ===========================================================================

class TestBuildCmdResponse:
    def _make_step_result(self, order=1, title="step", passed=True, exit_code=0, summary="ok"):
        sr = MagicMock()
        sr.step.order = order
        sr.step.title = title
        sr.verification.passed = passed
        sr.verification.summary = summary
        sr.execution.exit_code = exit_code
        return sr

    def test_builds_response_with_steps(self, gateway_module):
        orch_result = _FakeOrchResult(
            step_results=[self._make_step_result(1, "Build", True, 0, "OK")],
            total_steps=1,
            completed_steps=1,
            failed_steps=0,
        )
        mock_orch = MagicMock()
        mock_orch.telemetry.get_trace.return_value = None

        response = gateway_module._build_cmd_response(orch_result, "deploy app", mock_orch)

        assert response.goal == "deploy app"
        assert response.total_steps == 1
        assert response.completed_steps == 1
        assert response.failed_steps == 0
        assert len(response.steps) == 1
        assert response.steps[0].title == "Build"
        assert response.steps[0].passed is True

    def test_trace_included_when_available(self, gateway_module):
        orch_result = _FakeOrchResult()
        mock_orch = MagicMock()
        # telemetry returns a dataclass-able object
        fake_trace = MagicMock()
        mock_orch.telemetry.get_trace.return_value = fake_trace

        with patch("src.core.gateway.gateway_main.asdict", return_value={"key": "value"}):
            response = gateway_module._build_cmd_response(orch_result, "goal", mock_orch)

        assert response.trace == {"key": "value"}

    def test_trace_none_when_not_available(self, gateway_module):
        orch_result = _FakeOrchResult()
        mock_orch = MagicMock()
        mock_orch.telemetry.get_trace.return_value = None

        response = gateway_module._build_cmd_response(orch_result, "goal", mock_orch)
        assert response.trace is None

    def test_status_propagated(self, gateway_module):
        orch_result = _FakeOrchResult(status=_FakeStatus.FAILED, completed_steps=0, failed_steps=3)
        mock_orch = MagicMock()
        mock_orch.telemetry.get_trace.return_value = None

        response = gateway_module._build_cmd_response(orch_result, "goal", mock_orch)
        assert response.status == "failed"


# ===========================================================================
# FastAPI endpoint tests via TestClient
# ===========================================================================

class TestHealthEndpoint:
    def test_health_returns_ok(self, gateway_module):
        client = TestClient(gateway_module.app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_has_engine_field(self, gateway_module):
        client = TestClient(gateway_module.app)
        resp = client.get("/health")
        data = resp.json()
        assert "engine" in data


class TestPresetsEndpoint:
    def test_presets_returns_list(self, gateway_module):
        client = TestClient(gateway_module.app)
        resp = client.get("/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_presets_have_required_fields(self, gateway_module):
        client = TestClient(gateway_module.app)
        resp = client.get("/presets")
        data = resp.json()
        if data:
            preset = data[0]
            assert "id" in preset
            assert "label" in preset
            assert "goal" in preset


class TestProjectsEndpoint:
    def test_projects_returns_list(self, gateway_module):
        client = TestClient(gateway_module.app)
        resp = client.get("/projects")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestDashboardEndpoint:
    def test_dashboard_returns_html(self, gateway_module):
        client = TestClient(gateway_module.app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_has_version(self, gateway_module):
        client = TestClient(gateway_module.app)
        resp = client.get("/")
        assert gateway_module.VERSION in resp.text


class TestCmdEndpoint:
    def _make_mock_result(self):
        result = _FakeOrchResult(
            status=_FakeStatus.SUCCESS,
            total_steps=1,
            completed_steps=1,
            failed_steps=0,
        )
        return result

    def test_cmd_missing_token_env_returns_500(self, gateway_module):
        client = TestClient(gateway_module.app, raise_server_exceptions=False)
        env = {k: v for k, v in os.environ.items() if k != "MEKONG_API_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            resp = client.post("/cmd", json={"goal": "deploy", "token": "any"})
        assert resp.status_code == 500

    def test_cmd_invalid_token_returns_401(self, gateway_module):
        client = TestClient(gateway_module.app, raise_server_exceptions=False)
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "correct"}):
            resp = client.post("/cmd", json={"goal": "deploy", "token": "wrong"})
        assert resp.status_code == 401

    def test_cmd_valid_token_executes(self, gateway_module):
        mock_result = self._make_mock_result()
        mock_orch_instance = MagicMock()
        mock_orch_instance.run_from_goal.return_value = mock_result
        mock_orch_instance.telemetry.get_trace.return_value = None

        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "testtoken"}):
            with patch(f"{PATCH_BASE}._build_orchestrator", return_value=mock_orch_instance):
                client = TestClient(gateway_module.app)
                resp = client.post("/cmd", json={"goal": "run tests", "token": "testtoken"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["goal"] == "run tests"

    def test_cmd_orchestration_exception_returns_500(self, gateway_module):
        mock_orch_instance = MagicMock()
        mock_orch_instance.run_from_goal.side_effect = RuntimeError("boom")

        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "tok"}):
            with patch(f"{PATCH_BASE}._build_orchestrator", return_value=mock_orch_instance):
                client = TestClient(gateway_module.app, raise_server_exceptions=False)
                resp = client.post("/cmd", json={"goal": "fail", "token": "tok"})

        assert resp.status_code == 500


class TestMemoryEndpoints:
    """Memory endpoints use a closure-bound MemoryStore instance from create_app().
    We configure the mock that was installed during module patching.
    """

    def _configure_memory_mock(self, gateway_module, stats=None):
        """Configure the MemoryStore mock instance that was captured in app closure."""
        # The MemoryStore was patched at module level with MagicMock().
        # The app closure captured the instance returned by MemoryStore().
        # Access it via the patched class's return_value.
        mock_cls = _MODULE_PATCHES.get("src.core.memory_canonical.MemoryStore")
        if mock_cls is None:
            return MagicMock()
        instance = mock_cls.return_value

        entry = MagicMock()
        entry.goal = "test goal"
        entry.status = "success"
        entry.timestamp = 1700000000.0
        entry.duration_ms = 123.4
        entry.error_summary = ""
        entry.recipe_used = "recipe.md"

        instance.recent.return_value = [entry]
        instance.query.return_value = [entry]
        instance.stats.return_value = stats or {
            "total": 1, "success_rate": 100.0,
            "top_goals": ["test goal"], "recent_failures": 0,
        }
        return instance

    def test_memory_recent_returns_list(self, gateway_module):
        self._configure_memory_mock(gateway_module)
        client = TestClient(gateway_module.app)
        resp = client.get("/memory/recent")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_memory_stats_returns_object(self, gateway_module):
        self._configure_memory_mock(gateway_module, stats={
            "total": 5, "success_rate": 80.0,
            "top_goals": ["deploy"], "recent_failures": 1,
        })
        client = TestClient(gateway_module.app)
        resp = client.get("/memory/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "success_rate" in data

    def test_memory_search_with_query(self, gateway_module):
        self._configure_memory_mock(gateway_module)
        client = TestClient(gateway_module.app)
        resp = client.get("/memory/search?q=deploy")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_memory_search_empty_query_uses_recent(self, gateway_module):
        self._configure_memory_mock(gateway_module)
        client = TestClient(gateway_module.app)
        resp = client.get("/memory/search")
        assert resp.status_code == 200


class TestHaltEndpoint:
    def test_halt_valid_token(self, gateway_module):
        mock_gov = MagicMock()
        mock_gov_cls = MagicMock(return_value=mock_gov)
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "haltme"}):
            # Governance is imported lazily inside the endpoint handler
            with patch.dict("sys.modules", {"src.core.governance": MagicMock(Governance=mock_gov_cls)}):
                client = TestClient(gateway_module.app)
                resp = client.post("/halt", json={"token": "haltme"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "halted"

    def test_halt_invalid_token_returns_401(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "correct"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.post("/halt", json={"token": "wrong"})
        assert resp.status_code == 401

    def test_halt_missing_env_returns_500(self, gateway_module):
        env = {k: v for k, v in os.environ.items() if k != "MEKONG_API_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.post("/halt", json={"token": "any"})
        assert resp.status_code == 500


class TestTelegramStatusEndpoint:
    def test_telegram_not_configured(self, gateway_module):
        env = {k: v for k, v in os.environ.items() if k != "MEKONG_TELEGRAM_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            client = TestClient(gateway_module.app)
            resp = client.get("/telegram/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False

    def test_telegram_configured_shows_true(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_TELEGRAM_TOKEN": "bot123:TOKEN"}):
            client = TestClient(gateway_module.app)
            resp = client.get("/telegram/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True


class TestScheduleEndpoints:
    """Scheduler is closure-bound. Configure via the patched Scheduler class's return_value."""

    def _get_scheduler_mock(self):
        mock_cls = _MODULE_PATCHES.get("src.core.scheduler.Scheduler")
        return mock_cls.return_value if mock_cls else MagicMock()

    def _make_job(self):
        job = MagicMock()
        job.id = "job-123"
        job.name = "nightly"
        job.goal = "run cleanup"
        job.job_type = "daily"
        job.interval_seconds = 300
        job.daily_time = "02:00"
        job.enabled = True
        job.last_run = None
        job.next_run = None
        job.run_count = 0
        return job

    def test_add_job_returns_job_info(self, gateway_module):
        mock_sched = self._get_scheduler_mock()
        mock_sched.add_job.return_value = self._make_job()

        client = TestClient(gateway_module.app)
        resp = client.post("/schedule/jobs", json={
            "name": "nightly", "goal": "run cleanup",
            "job_type": "daily", "interval_seconds": 300, "daily_time": "02:00",
        })
        assert resp.status_code == 200

    def test_list_jobs_returns_list(self, gateway_module):
        mock_sched = self._get_scheduler_mock()
        mock_sched.list_jobs.return_value = []

        client = TestClient(gateway_module.app)
        resp = client.get("/schedule/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_remove_nonexistent_job_returns_404(self, gateway_module):
        mock_sched = self._get_scheduler_mock()
        mock_sched.remove_job.return_value = False

        client = TestClient(gateway_module.app, raise_server_exceptions=False)
        resp = client.delete("/schedule/jobs/nonexistent")
        assert resp.status_code == 404


class TestSwarmEndpoints:
    """Swarm endpoints are gated by require_swarm_token (X-API-Key header).

    SwarmRegistry is closure-bound. Configure via patched class return_value.
    """

    SWARM_HEADERS = {"X-API-Key": "swarm-token"}

    def _get_registry_mock(self):
        mock_cls = _MODULE_PATCHES.get("src.core.swarm.SwarmRegistry")
        return mock_cls.return_value if mock_cls else MagicMock()

    def _make_node(self):
        node = MagicMock()
        node.id = "node-abc"
        node.name = "worker-1"
        node.host = "192.168.1.10"
        node.port = 8000
        node.token = "tok"
        node.status = "online"
        node.last_heartbeat = 0
        return node

    def test_register_node_returns_info(self, gateway_module):
        mock_reg = self._get_registry_mock()
        mock_reg.register_node.return_value = self._make_node()

        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "swarm-token"}):
            client = TestClient(gateway_module.app)
            resp = client.post("/swarm/register", json={
                "name": "worker-1", "host": "192.168.1.10",
                "port": 8000, "token": "tok",
            }, headers=self.SWARM_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "worker-1"

    def test_register_without_token_returns_401(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "swarm-token"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.post("/swarm/register", json={
                "name": "worker-1", "host": "192.168.1.10",
                "port": 8000, "token": "tok",
            })
        assert resp.status_code == 401

    def test_register_with_wrong_token_returns_401(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "correct"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.post("/swarm/register", json={
                "name": "worker-1", "host": "192.168.1.10",
                "port": 8000, "token": "tok",
            }, headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_list_nodes_without_token_returns_401(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "swarm-token"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.get("/swarm/nodes")
        assert resp.status_code == 401

    def test_remove_nonexistent_node_returns_404(self, gateway_module):
        mock_reg = self._get_registry_mock()
        mock_reg.remove_node.return_value = False

        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "swarm-token"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.delete("/swarm/nodes/missing", headers=self.SWARM_HEADERS)
        assert resp.status_code == 404

    def test_dispatch_nonexistent_node_returns_404(self, gateway_module):
        mock_reg = self._get_registry_mock()
        mock_reg.get_node.return_value = None

        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "swarm-token"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.post("/swarm/dispatch", json={
                "node_id": "missing", "goal": "do something",
            }, headers=self.SWARM_HEADERS)
        assert resp.status_code == 404

    def test_dispatch_without_token_returns_401(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "swarm-token"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.post("/swarm/dispatch", json={
                "node_id": "missing", "goal": "do something",
            })
        assert resp.status_code == 401

    def test_dispatch_via_query_token_returns_404(self, gateway_module):
        """A token in the ``?token=`` query parameter satisfies the dependency.

        Backward-compat path: callers that send the credential as a query
        string instead of the ``X-API-Key`` header are still authenticated.
        """
        mock_reg = self._get_registry_mock()
        mock_reg.get_node.return_value = None

        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "swarm-token"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.post(
                "/swarm/dispatch?token=swarm-token",
                json={"node_id": "missing", "goal": "do something"},
            )
        assert resp.status_code == 404

    def test_register_via_query_token_returns_info(self, gateway_module):
        """Same backward-compat path on the register endpoint."""
        mock_reg = self._get_registry_mock()
        mock_reg.register_node.return_value = self._make_node()

        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "swarm-token"}):
            client = TestClient(gateway_module.app)
            resp = client.post(
                "/swarm/register?token=swarm-token",
                json={
                    "name": "worker-1", "host": "192.168.1.10",
                    "port": 8000, "token": "tok",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "worker-1"

    def test_dispatch_with_wrong_query_token_returns_401(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "correct"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.post(
                "/swarm/dispatch?token=wrong",
                json={"node_id": "missing", "goal": "do something"},
            )
        assert resp.status_code == 401

    def test_remove_without_token_returns_401(self, gateway_module):
        """swarm_remove_node now requires the swarm token like the others."""
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "swarm-token"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.delete("/swarm/nodes/missing")
        assert resp.status_code == 401

    def test_remove_with_wrong_token_returns_401(self, gateway_module):
        with patch.dict(os.environ, {"MEKONG_API_TOKEN": "swarm-token"}):
            client = TestClient(gateway_module.app, raise_server_exceptions=False)
            resp = client.delete(
                "/swarm/nodes/missing", headers={"X-API-Key": "wrong"}
            )
        assert resp.status_code == 401


class TestAgiProxyEndpoints:
    def test_agi_health_offline(self, gateway_module):
        """When AGI daemon unreachable, returns offline status."""
        import httpx
        from unittest.mock import AsyncMock

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = TestClient(gateway_module.app)
            resp = client.get("/api/agi/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "offline"

    def test_agi_health_endpoint_exists(self, gateway_module):
        from unittest.mock import AsyncMock
        import httpx

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            client = TestClient(gateway_module.app)
            # Even if daemon is offline, endpoint should respond (not 404)
            resp = client.get("/api/agi/health")
        assert resp.status_code != 404
