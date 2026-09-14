import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.eclipse_package import handler_java, materialize_eclipse_package, plugin_xml


def test_eclipse_plugin_xml_declares_commands_and_handlers() -> None:
    source = plugin_xml(build_command_catalog())

    assert '<extension point="org.eclipse.ui.commands">' in source
    assert '<extension point="org.eclipse.ui.handlers">' in source
    assert "com.mekong.commandfabric.cook" in source


def test_eclipse_handler_runs_local_command() -> None:
    source = handler_java(build_command_catalog())

    assert "extends AbstractHandler" in source
    assert "ProcessBuilder" in source
    assert "buildArgv" in source
    assert '"/bin/sh"' not in source
    assert '"-lc"' not in source
    assert 'COMMANDS.put("cook"' in source


def test_eclipse_package_materializes_plugin_scaffold(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_eclipse_package(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.eclipse_package.v1"
    assert payload["command_count"] == len(records)
    assert (tmp_path / "plugin.xml").exists()
    assert (tmp_path / "pom.xml").exists()
    manifest = json.loads((tmp_path / "data" / "eclipse.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "mekong.command_fabric.adapter.eclipse.v1"


def test_materialize_eclipse_package_default(tmp_path) -> None:
    payload = materialize_eclipse_package(tmp_path)

    assert payload["artifact_count"] == 7
    assert (tmp_path / "README.md").exists()

