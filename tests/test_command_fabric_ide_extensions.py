import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.ide_extensions import (
    extension_package_json,
    materialize_ide_extension,
)
from src.command_fabric.jetbrains_extension import action_kt, plugin_xml


def test_ide_extension_package_json_contributes_commands() -> None:
    records = build_command_catalog()
    package = extension_package_json("vscode", records)

    assert package["name"] == "mekong-command-fabric-vscode"
    contributes = package["contributes"]
    assert any(command["command"] == "mekong.cook" for command in contributes["commands"])
    assert "onCommand:mekong.cook" in package["activationEvents"]


def test_command_fabric_materializes_vscode_extension(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_ide_extension(tmp_path, "vscode", records=records)

    extension_root = tmp_path / "vscode"
    assert payload["schema"] == "mekong.command_fabric.ide_extension.v1"
    assert payload["host"] == "vscode"
    assert payload["command_count"] == len(records)
    assert (extension_root / "package.json").exists()
    assert (extension_root / "src" / "extension.ts").exists()
    assert (extension_root / "build-package.sh").exists()
    assert "npm run compile" in (extension_root / "build-package.sh").read_text(encoding="utf-8")
    package = json.loads((extension_root / "package.json").read_text(encoding="utf-8"))
    assert any(command["command"] == "mekong.plan" for command in package["contributes"]["commands"])


def test_command_fabric_materializes_cursor_extension(tmp_path) -> None:
    payload = materialize_ide_extension(tmp_path, "cursor")

    assert payload["host"] == "cursor"
    assert (tmp_path / "cursor" / "package.json").exists()
    assert (tmp_path / "cursor" / "src" / "extension.ts").exists()
    assert (tmp_path / "cursor" / "BUILD.md").exists()


def test_command_fabric_materializes_windsurf_extension(tmp_path) -> None:
    payload = materialize_ide_extension(tmp_path, "windsurf", records=build_command_catalog())

    root = tmp_path / "windsurf"
    assert payload["host"] == "windsurf"
    assert (root / "package.json").exists()
    assert (root / "src" / "extension.ts").exists()
    assert "npm run package" in (root / "build-package.sh").read_text(encoding="utf-8")


def test_command_fabric_materializes_theia_extension(tmp_path) -> None:
    payload = materialize_ide_extension(tmp_path, "theia")

    root = tmp_path / "theia"
    assert payload["host"] == "theia"
    assert (root / "package.json").exists()
    assert (root / "src" / "extension.ts").exists()
    assert "npm run package" in (root / "build-package.sh").read_text(encoding="utf-8")


def test_jetbrains_plugin_xml_contributes_actions() -> None:
    records = build_command_catalog()
    plugin = plugin_xml(records)

    assert "<id>com.mekong.commandfabric</id>" in plugin
    assert 'id="MekongCookAction"' in plugin
    assert 'text="Mekong: cook"' in plugin


def test_jetbrains_action_runs_command_in_ide_console() -> None:
    records = build_command_catalog()
    source = action_kt(records)

    assert "RunContentExecutor(project, handler)" in source
    assert "GeneralCommandLine(argv)" in source
    assert '"/bin/sh"' not in source
    assert '"-lc"' not in source
    assert '"MekongCookAction" to MekongCommand("cook"' in source


def test_command_fabric_materializes_jetbrains_extension(tmp_path) -> None:
    payload = materialize_ide_extension(tmp_path, "jetbrains")

    root = tmp_path / "jetbrains"
    assert payload["host"] == "jetbrains"
    assert (root / "build.gradle.kts").exists()
    assert (root / "src" / "main" / "resources" / "META-INF" / "plugin.xml").exists()
    assert (
        root
        / "src"
        / "main"
        / "kotlin"
        / "com"
        / "mekong"
        / "commandfabric"
        / "MekongCommandAction.kt"
    ).exists()
    assert "gradle buildPlugin" in (root / "build-package.sh").read_text(encoding="utf-8")

