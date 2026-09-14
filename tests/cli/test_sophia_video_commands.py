# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""CLI tests for Sophia AI Video Factory commands (Funnel 3).

Covers:
- Typer subcommand registration under tools_app (mekong tools video)
- Direct sophia_app execution and help output
- `render` and `create` commands with dry-run, options, and file input
- `status` command (success, not found, invalid ID)
- `list` command (table output, JSON mode, empty state)
- `avatars`, `voices`, `templates` discovery commands
- `cost` estimation command
- Security validation & input rejection (script bounds, forbidden characters, flag smuggling)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.tools_browse_collab_commands import tools_app
from src.commands.sophia_video import app as sophia_app
from src.services.sophia_video_service import SophiaVideoService

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect SophiaVideoService default storage to a temp directory during tests."""
    temp_dir = tmp_path / "sophia_test_data"
    temp_dir.mkdir(parents=True, exist_ok=True)
    test_svc = SophiaVideoService(storage_dir=temp_dir, enable_billing=False)
    monkeypatch.setattr("src.commands.sophia_video._service", test_svc)
    return temp_dir


# ---------------------------------------------------------------------------
# Registration and Help Tests
# ---------------------------------------------------------------------------

class TestSophiaCliRegistration:
    """Verify registration under tools and standalone help output."""

    def test_tools_video_help(self) -> None:
        result = runner.invoke(tools_app, ["video", "--help"])
        assert result.exit_code == 0
        assert "Sophia AI Video Factory" in result.output
        assert "render" in result.output
        assert "create" in result.output
        assert "status" in result.output
        assert "list" in result.output
        assert "avatars" in result.output
        assert "voices" in result.output
        assert "templates" in result.output
        assert "cost" in result.output

    def test_sophia_app_direct_help(self) -> None:
        result = runner.invoke(sophia_app, ["--help"])
        assert result.exit_code == 0
        assert "Sophia AI Video Factory" in result.output


# ---------------------------------------------------------------------------
# Render & Create Commands
# ---------------------------------------------------------------------------

class TestSophiaRenderCommands:
    """Verify video render command execution and error handling."""

    def test_render_dry_run_success(self) -> None:
        script = "Chào mừng quý khách đến với dịch vụ tư vấn thuế tự động của Mekong."
        result = runner.invoke(
            sophia_app,
            [
                "render",
                script,
                "--title", "Tax Overview Video",
                "--ratio", "9:16",
                "--template", "news_anchor",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Video Render Completed Successfully!" in result.output
        assert "Tax Overview Video" in result.output
        assert "9:16" in result.output

    def test_create_alias_with_json_output(self) -> None:
        script = "Hướng dẫn lập báo cáo tài chính và quyết toán thuế cuối năm."
        result = runner.invoke(
            sophia_app,
            [
                "create",
                script,
                "--title", "Financial Report Guide",
                "--dry-run",
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Financial Report Guide"
        assert data["status"] == "COMPLETED"
        assert data["job_id"].startswith("sophia-")

    def test_render_from_script_file(self, tmp_path: Path) -> None:
        script_file = tmp_path / "marketing_script.txt"
        script_content = "Nội dung kịch bản quảng cáo sản phẩm được tải từ tệp tin cục bộ."
        script_file.write_text(script_content, encoding="utf-8")

        result = runner.invoke(
            sophia_app,
            [
                "render",
                str(script_file),
                "--title", "File Script Video",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "File Script Video" in result.output

    def test_render_rejects_short_script(self) -> None:
        result = runner.invoke(sophia_app, ["render", "Short", "--dry-run"])
        assert result.exit_code == 1
        assert "Validation Error" in result.output
        assert "too short" in result.output

    def test_render_rejects_forbidden_characters(self) -> None:
        unsafe_script = "Kịch bản chứa ký tự nguy hiểm ; rm -rf /"
        result = runner.invoke(sophia_app, ["render", unsafe_script, "--dry-run"])
        assert result.exit_code == 1
        assert "Forbidden character" in result.output

    def test_render_rejects_unsupported_aspect_ratio(self) -> None:
        script = "Kịch bản thử nghiệm tỷ lệ khung hình không hợp lệ."
        result = runner.invoke(sophia_app, ["render", script, "--ratio", "4:3", "--dry-run"])
        assert result.exit_code == 1
        assert "Unsupported aspect ratio" in result.output

    def test_render_rejects_flag_as_script(self) -> None:
        result = runner.invoke(sophia_app, ["render", "--", "--malicious-flag"])
        assert result.exit_code == 1
        assert "Invalid script argument or option flag" in result.output


# ---------------------------------------------------------------------------
# Status Command
# ---------------------------------------------------------------------------

class TestSophiaStatusCommand:
    """Verify job status queries."""

    def test_status_existing_job(self) -> None:
        # First render a video to have a valid job
        script = "Kịch bản tạo video để kiểm tra lệnh tra cứu trạng thái."
        render_res = runner.invoke(sophia_app, ["render", script, "--title", "Status Check", "--dry-run", "--json"])
        job_data = json.loads(render_res.output)
        job_id = job_data["job_id"]

        # Now query status
        status_res = runner.invoke(sophia_app, ["status", job_id])
        assert status_res.exit_code == 0
        assert job_id in status_res.output
        assert "Status Check" in status_res.output

    def test_status_with_json_output(self) -> None:
        script = "Kịch bản tạo video để kiểm tra trạng thái dạng JSON."
        render_res = runner.invoke(sophia_app, ["render", script, "--dry-run", "--json"])
        job_id = json.loads(render_res.output)["job_id"]

        status_res = runner.invoke(sophia_app, ["status", job_id, "--json"])
        assert status_res.exit_code == 0
        data = json.loads(status_res.output)
        assert data["job_id"] == job_id
        assert data["status"] == "COMPLETED"

    def test_status_not_found(self) -> None:
        result = runner.invoke(sophia_app, ["status", "sophia-nonexistent-12345678"])
        assert result.exit_code == 1
        assert "Job not found" in result.output

    def test_status_invalid_id(self) -> None:
        result = runner.invoke(sophia_app, ["status", "invalid_id_format"])
        assert result.exit_code == 1
        assert "Invalid Job ID" in result.output


# ---------------------------------------------------------------------------
# List Command
# ---------------------------------------------------------------------------

class TestSophiaListCommand:
    """Verify listing recent video jobs."""

    def test_list_empty(self) -> None:
        result = runner.invoke(sophia_app, ["list", "--tenant", "nonexistent-tenant"])
        assert result.exit_code == 0
        assert "No video jobs found" in result.output

    def test_list_with_rendered_jobs(self) -> None:
        script = "Kịch bản tạo video để kiểm tra danh sách jobs."
        runner.invoke(sophia_app, ["render", script, "--title", "Listable Video", "--tenant", "tenant-alpha", "--dry-run"])

        result = runner.invoke(sophia_app, ["list", "--tenant", "tenant-alpha"])
        assert result.exit_code == 0
        assert "Listable" in result.output

    def test_list_with_json(self) -> None:
        script = "Kịch bản kiểm tra xuất danh sách dạng JSON."
        runner.invoke(sophia_app, ["render", script, "--title", "JSON Video", "--tenant", "tenant-beta", "--dry-run"])

        result = runner.invoke(sophia_app, ["list", "--tenant", "tenant-beta", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["title"] == "JSON Video"


# ---------------------------------------------------------------------------
# Discovery Commands: Avatars, Voices, Templates, Cost
# ---------------------------------------------------------------------------

class TestSophiaDiscoveryCommands:
    """Verify discovery utilities."""

    def test_avatars_command(self) -> None:
        result = runner.invoke(sophia_app, ["avatars"])
        assert result.exit_code == 0
        assert "Sophia News" in result.output
        assert "Minh Trí" in result.output

    def test_avatars_filter_gender(self) -> None:
        result = runner.invoke(sophia_app, ["avatars", "--gender", "female", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(a["gender"] == "female" for a in data)

    def test_voices_command(self) -> None:
        result = runner.invoke(sophia_app, ["voices"])
        assert result.exit_code == 0
        assert "Hoàng Nam" in result.output
        assert "Mai Linh" in result.output

    def test_voices_filter_lang(self) -> None:
        result = runner.invoke(sophia_app, ["voices", "--lang", "vi", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all("vi" in v["language"].lower() for v in data)

    def test_templates_command(self) -> None:
        result = runner.invoke(sophia_app, ["templates"])
        assert result.exit_code == 0
        assert "news_anchor" in result.output
        assert "faceless" in result.output

    def test_cost_command_success(self) -> None:
        result = runner.invoke(sophia_app, ["cost", "45", "--template", "news_anchor"])
        assert result.exit_code == 0
        assert "Estimated Video Rendering Cost" in result.output
        assert "100 MCU" in result.output

    def test_cost_command_json(self) -> None:
        result = runner.invoke(sophia_app, ["cost", "60", "--template", "youtube_deepdive", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["estimated_mcu"] == 150
        assert data["duration_seconds"] == 60

    def test_cost_command_invalid_duration(self) -> None:
        result = runner.invoke(sophia_app, ["cost", "--", "-10"])
        assert result.exit_code == 1
        assert "Invalid Input" in result.output
