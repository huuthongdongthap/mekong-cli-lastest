import json

from src.command_fabric.artifacts import materialize_command_fabric
from src.command_fabric.adapters import SUPPORTED_ADAPTERS
from src.command_fabric.runtime import (
    command_fabric_manifest,
    invoke_command_fabric,
    records_for_scope,
)


def test_command_fabric_materializes_adapter_artifacts(tmp_path) -> None:
    payload = materialize_command_fabric(
        output_dir=tmp_path,
        scope="project",
        adapters=["mcp", "vscode"],
    )

    assert payload["schema"] == "mekong.command_fabric.artifacts.v1"
    assert payload["scope"] == "project"
    assert payload["artifact_count"] == 5
    assert (tmp_path / "canonical.json").exists()
    assert (tmp_path / "mcp.json").exists()
    assert (tmp_path / "vscode.json").exists()
    assert (tmp_path / "adapters.json").exists()
    assert (tmp_path / "command-packs.json").exists()

    mcp_payload = json.loads((tmp_path / "mcp.json").read_text(encoding="utf-8"))
    assert mcp_payload["schema"] == "mekong.command_fabric.adapter.mcp.v1"
    assert mcp_payload["tool_count"] == len(records_for_scope("project"))

    bundle = json.loads((tmp_path / "adapters.json").read_text(encoding="utf-8"))
    assert bundle["schema"] == "mekong.command_fabric.adapter_bundle.v1"
    assert bundle["adapter_count"] == 2
    assert set(bundle["adapters"]) == {"mcp", "vscode"}


def test_command_fabric_materializes_shell_adapter_artifacts(tmp_path) -> None:
    payload = materialize_command_fabric(
        output_dir=tmp_path,
        scope="project",
        adapters=["shell"],
    )

    assert payload["artifact_count"] == 4
    assert (tmp_path / "canonical.json").exists()
    assert (tmp_path / "shell.json").exists()
    assert (tmp_path / "adapters.json").exists()
    assert (tmp_path / "command-packs.json").exists()


def test_command_fabric_materializes_deploy_ready_adapter_bundle(tmp_path) -> None:
    payload = materialize_command_fabric(output_dir=tmp_path, scope="project")

    assert payload["artifact_count"] == len(SUPPORTED_ADAPTERS) + 2
    bundle = json.loads((tmp_path / "adapters.json").read_text(encoding="utf-8"))
    assert bundle["schema"] == "mekong.command_fabric.adapter_bundle.v1"
    assert bundle["adapter_count"] == len(SUPPORTED_ADAPTERS) - 1
    assert set(bundle["adapters"]) == set(SUPPORTED_ADAPTERS) - {"canonical"}


def test_command_fabric_runtime_lists_project_mcp_tools() -> None:
    payload = command_fabric_manifest(adapter="mcp", scope="project")

    assert payload["schema"] == "mekong.command_fabric.adapter.mcp.v1"
    assert payload["tool_count"] == len(records_for_scope("project"))
    assert any(tool["name"] == "mekong_cook" for tool in payload["tools"])


def test_command_fabric_runtime_catalog_only_command_does_not_recurse() -> None:
    result = invoke_command_fabric("4-project", scope="project")

    assert result.exit_code == 0
    assert result.mode == "catalog-only"
    assert ".claude/commands/4-project.md" in result.stdout


def test_command_fabric_runtime_can_invoke_native_command() -> None:
    result = invoke_command_fabric("harness-eval", args="--json", scope="project")

    assert result.exit_code == 0
    assert result.mode == "executed"
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["suite"] == "solo-ceo-harness"
    assert payload["passed"] is True


def test_mcp_server_exposes_command_fabric_handlers() -> None:
    from src.core.mcp_server import MekongMcpServer

    server = MekongMcpServer()
    listed = json.loads(server._handle_command_fabric_list(scope="project", adapter="mcp"))
    assert listed["ok"] is True
    assert listed["data"]["schema"] == "mekong.command_fabric.adapter.mcp.v1"

    invoked = json.loads(server._handle_command_fabric_run("4-project"))
    assert invoked["ok"] is True
    assert invoked["data"]["mode"] == "catalog-only"

    invalid_scope = json.loads(server._handle_command_fabric_run("4-project", scope="invalid"))
    assert invalid_scope["ok"] is False
    assert "Invalid scope" in invalid_scope["error"]

    malicious_cmd = json.loads(server._handle_command_fabric_run("4-project; rm -rf /"))
    assert malicious_cmd["ok"] is False
    assert "Invalid command name" in malicious_cmd["error"]

    malicious_args = json.loads(server._handle_command_fabric_run("4-project", args="--opt; echo bad"))
    assert malicious_args["ok"] is False
    assert "forbidden control or shell metacharacters" in malicious_args["error"]
