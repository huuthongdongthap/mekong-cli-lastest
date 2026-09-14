import json

import pytest

from src.command_fabric.agent_cli_package import command_markdown, materialize_agent_cli_package
from src.command_fabric.artifacts import materialize_agent_cli_packages
from src.command_fabric.catalog import build_command_catalog


def test_agent_cli_command_markdown_uses_catalog_metadata() -> None:
    record = next(item for item in build_command_catalog() if item.name == "cook")
    content = command_markdown(record, "opencode")

    assert 'adapter: "opencode"' in content
    assert "# cook" in content
    assert "python3 -m src.main cook $ARGUMENTS" in content


def test_agent_cli_package_materializes_markdown_commands(tmp_path) -> None:
    payload = materialize_agent_cli_package(tmp_path, "gemini-cli", build_command_catalog())

    root = tmp_path / "gemini-cli"
    assert payload["host"] == "gemini-cli"
    assert (root / "manifest.json").exists()
    assert (root / "commands" / "cook.md").exists()
    assert "mekong.command_fabric.adapter.gemini-cli.v1" in (
        root / "manifest.json"
    ).read_text(encoding="utf-8")


def test_codex_package_materializes_manifest_and_readme(tmp_path) -> None:
    payload = materialize_agent_cli_package(tmp_path, "codex", build_command_catalog())

    root = tmp_path / "codex"
    assert payload["host"] == "codex"
    assert (root / "manifest.json").exists()
    assert (root / "README.md").exists()
    assert "Mekong Codex Command Cards" in (root / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "host",
    ["aider", "continue-dev", "copilot-cli", "cursor-agent", "amp", "goose", "crush", "kiro-cli"],
)
def test_manifest_agent_cli_packages_materialize_command_cards(tmp_path, host: str) -> None:
    payload = materialize_agent_cli_package(tmp_path, host, build_command_catalog())

    root = tmp_path / host
    assert payload["host"] == host
    assert (root / "manifest.json").exists()
    assert (root / "README.md").exists()
    assert not (root / "commands").exists()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["adapter"] == host


def test_agent_cli_packages_reject_unknown_host(tmp_path) -> None:
    with pytest.raises(ValueError, match="Unsupported agent CLI hosts"):
        materialize_agent_cli_packages(tmp_path, hosts=["unknown"])


def test_materialize_agent_cli_package_materializes_opencode(tmp_path) -> None:
    payload = materialize_agent_cli_packages(
        output_dir=tmp_path,
        scope="project",
        hosts=["opencode"],
    )

    assert payload["package_count"] == 1
    assert payload["packages"][0]["host"] == "opencode"
    assert (tmp_path / "opencode" / "commands" / "cook.md").exists()


def test_materialize_all_default_agent_cli_packages(tmp_path) -> None:
    payload = materialize_agent_cli_packages(
        output_dir=tmp_path,
        scope="project",
    )

    hosts = {package["host"] for package in payload["packages"]}
    assert payload["package_count"] == 12
    assert hosts == {
        "claude-code",
        "gemini-cli",
        "opencode",
        "codex",
        "aider",
        "continue-dev",
        "copilot-cli",
        "cursor-agent",
        "amp",
        "goose",
        "crush",
        "kiro-cli",
    }
