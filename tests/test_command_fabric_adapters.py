from src.command_fabric.adapters import export_adapter_manifest
from src.command_fabric.catalog import build_command_catalog


def test_command_fabric_exports_agent_cli_adapters() -> None:
    records = build_command_catalog()

    for adapter in (
        "claude-code",
        "codex",
        "gemini-cli",
        "opencode",
        "cursor-agent",
        "amp",
        "goose",
        "crush",
        "kiro-cli",
    ):
        payload = export_adapter_manifest(adapter, records)
        assert payload["schema"] == f"mekong.command_fabric.adapter.{adapter}.v1"
        assert payload["command_count"] == len(records)
        cook = next(command for command in payload["commands"] if command["id"] == "cook")
        assert cook["execution"].startswith("python3 -m src.main cook")
        assert cook["source"] == ".claude/commands/cook.md"


def test_command_fabric_exports_ide_command_palette_adapters() -> None:
    records = build_command_catalog()

    for adapter in (
        "vscode",
        "cursor",
        "windsurf",
        "theia",
        "jetbrains",
        "visual-studio",
        "eclipse",
        "fleet",
        "nova",
        "lapce",
        "kakoune",
        "micro",
        "vim",
        "neovim",
        "helix",
        "zed",
        "emacs",
        "sublime",
    ):
        payload = export_adapter_manifest(adapter, records)
        assert payload["schema"] == f"mekong.command_fabric.adapter.{adapter}.v1"
        assert payload["command_count"] == len(records)
        plan = next(command for command in payload["commands"] if command["arguments"]["name"] == "plan")
        assert plan["command"] == "mekong.plan"
        assert plan["host"] == adapter


def test_command_fabric_exports_mcp_and_shell_adapters() -> None:
    records = build_command_catalog()
    mcp_payload = export_adapter_manifest("mcp", records)
    shell_payload = export_adapter_manifest("shell", records)

    assert mcp_payload["schema"] == "mekong.command_fabric.adapter.mcp.v1"
    assert mcp_payload["tool_count"] == len(records)
    assert any(tool["name"] == "mekong_cook" for tool in mcp_payload["tools"])

    assert shell_payload["schema"] == "mekong.command_fabric.adapter.shell.v1"
    assert shell_payload["command_count"] == len(records)
    assert any(command["completion"] == "mekong cook" for command in shell_payload["commands"])


