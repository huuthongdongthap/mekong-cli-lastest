from typer.testing import CliRunner

from src.cli.app_setup import build_app
from src.command_fabric.catalog import (
    build_command_catalog,
    build_global_command_catalog,
    export_command_catalog,
)
from src.command_fabric.packs import export_command_packs, validate_command_packs


def test_command_fabric_catalog_reads_command_markdown() -> None:
    records = build_command_catalog()
    by_name = {record.name: record for record in records}

    assert "cook" in by_name
    assert by_name["cook"].source == ".claude/commands/cook.md"
    assert "Implement features" in by_name["cook"].description
    assert by_name["cook"].execution.startswith("python3 -m src.main cook")
    assert "claude-code" in by_name["cook"].portability_targets
    assert "kiro-cli" in by_name["cook"].portability_targets
    assert "vscode" in by_name["cook"].portability_targets
    assert {
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
        "shell",
    } <= set(by_name["cook"].portability_targets)


def test_command_fabric_joins_optional_factory_contract() -> None:
    records = build_command_catalog()
    ask = next(record for record in records if record.name == "ask")

    assert ask.contract == "factory/contracts/commands/ask.json"
    assert ask.layer == "ops"


def test_command_fabric_export_shape_is_stable() -> None:
    payload = export_command_catalog(build_command_catalog())

    assert payload["schema"] == "mekong.command_fabric.v1"
    assert payload["count"] == len(payload["commands"])
    names = {command["name"] for command in payload["commands"]}
    assert payload["count"] >= 90
    assert {"cook", "plan", "binh-phap"} <= names
    assert {
        "name",
        "source",
        "description",
        "argument_hint",
        "allowed_tools",
        "execution",
        "contract",
        "layer",
        "portability_targets",
    } == set(payload["commands"][0])


def test_global_command_fabric_merges_mekong_and_claudekit_commands() -> None:
    records = build_global_command_catalog()
    by_name = {record.name: record for record in records}

    assert len(records) > len(build_command_catalog())
    assert by_name["cook"].source == ".claude/commands/cook.md"
    assert by_name["marketing-campaign"].source == "~/.claude/commands/marketing-campaign.md"
    assert by_name["orchestrate"].source == "~/.claude/commands/orchestrate.md"


def test_command_fabric_exports_json() -> None:
    payload = export_command_catalog(build_global_command_catalog())

    assert payload["schema"] == "mekong.command_fabric.v1"
    assert any(command["name"] == "plan" for command in payload["commands"])
    assert any(command["name"] == "marketing-campaign" for command in payload["commands"])


def test_command_fabric_can_export_project_only_scope() -> None:
    payload = export_command_catalog(build_command_catalog())

    assert payload["schema"] == "mekong.command_fabric.v1"
    names = {command["name"] for command in payload["commands"]}
    assert "cook" in names
    assert "marketing-campaign" not in names


def test_command_fabric_does_not_overwrite_native_commands() -> None:
    result = CliRunner().invoke(build_app(), ["plan", "--help"])

    assert result.exit_code == 0
    assert "Plan generation from company init" in result.stdout
    assert "slash command" not in result.stdout


def test_command_pack_manifest_covers_root_surface() -> None:
    validation = validate_command_packs()
    payload = export_command_packs()

    assert validation.valid is True
    assert validation.root_count == 60
    assert validation.native_count == 60
    assert validation.uncovered_root_commands == []
    assert validation.stale_native_commands == []
    assert validation.duplicate_native_commands == []
    assert payload["validation"]["valid"] is True


def test_command_fabric_exports_command_packs_json() -> None:
    payload = export_command_packs()

    assert payload["schema"] == "mekong.command_packs.v1"
    assert payload["pack_count"] == 10
    assert payload["validation"]["valid"] is True
