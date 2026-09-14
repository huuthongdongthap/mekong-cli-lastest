import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.lightweight_editor_packages import (
    fleet_plugin_json,
    kakoune_rc,
    materialize_lightweight_editor_package,
    micro_plugin_lua,
    nova_extension_js,
    shell_runner,
)


def test_fleet_plugin_declares_commands() -> None:
    source = fleet_plugin_json(build_command_catalog())

    assert '"id": "mekong-command-fabric"' in source
    assert '"id": "mekong.cook"' in source


def test_nova_extension_registers_commands() -> None:
    source = nova_extension_js(build_command_catalog())

    assert "nova.commands.register" in source
    assert '"cook":' in source


def test_kakoune_rc_defines_commands() -> None:
    source = kakoune_rc(build_command_catalog())

    assert "define-command mekong-cook" in source
    assert "mekong-kakoune cook" in source


def test_micro_plugin_registers_mekong_command() -> None:
    source = micro_plugin_lua(build_command_catalog())

    assert 'config.MakeCommand("mekong"' in source
    assert "mekong-micro" in source


def test_shell_runner_executes_lightweight_editor_commands() -> None:
    source = shell_runner("lapce", build_command_catalog())

    assert 'HOST = "lapce"' in source
    assert "shlex.split" in source
    assert "subprocess.call" in source
    assert "shell=True" not in source
    assert "$ARGUMENTS" in source


def test_lightweight_editor_packages_materialize_all_hosts(tmp_path) -> None:
    records = build_command_catalog()
    for host in ("fleet", "nova", "lapce", "kakoune", "micro"):
        payload = materialize_lightweight_editor_package(tmp_path / host, host, records)

        assert payload["schema"] == f"mekong.command_fabric.{host.replace('-', '_')}_package.v1"
        assert payload["command_count"] == len(records)
        manifest = json.loads((tmp_path / host / "data" / f"{host}.json").read_text(encoding="utf-8"))
        assert manifest["schema"] == f"mekong.command_fabric.adapter.{host}.v1"


def test_materialize_lightweight_editor_package_default(tmp_path) -> None:
    payload = materialize_lightweight_editor_package(tmp_path, "kakoune")

    assert payload["host"] == "kakoune"
    assert (tmp_path / "kakrc").exists()

