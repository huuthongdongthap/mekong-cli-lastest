import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.sublime_package import materialize_sublime_package, plugin_py


def test_sublime_plugin_defines_window_command() -> None:
    source = plugin_py(build_command_catalog())

    assert "MekongCommandFabricRunCommand" in source
    assert "show_quick_panel" in source
    assert "shlex.split" in source
    assert "subprocess.Popen" in source
    assert "shell=True" not in source


def test_sublime_package_materializes_plugin_and_adapter_data(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_sublime_package(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.sublime_package.v1"
    assert payload["command_count"] == len(records)
    assert (tmp_path / "mekong_command_fabric.py").exists()
    assert (tmp_path / "Default.sublime-commands").exists()
    manifest = json.loads((tmp_path / "data" / "sublime.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "mekong.command_fabric.adapter.sublime.v1"


def test_sublime_package_materializes_default(tmp_path) -> None:
    payload = materialize_sublime_package(tmp_path)

    assert payload["schema"] == "mekong.command_fabric.sublime_package.v1"
    assert payload["artifact_count"] == 5
    assert payload["command_count"] == len(build_command_catalog())
