import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.helix_package import helix_config, helix_runner_script, materialize_helix_package


def test_helix_runner_executes_command_fabric_records() -> None:
    source = helix_runner_script(build_command_catalog())

    assert "COMMANDS = json.loads" in source
    assert "$ARGUMENTS" in source
    assert "shlex.split" in source
    assert "subprocess.call" in source
    assert "shell=True" not in source


def test_helix_config_contains_shell_bindings() -> None:
    source = helix_config(build_command_catalog())

    assert "[keys.normal.space.m]" in source
    assert ":sh mekong-helix" in source


def test_helix_package_materializes_runner_and_config(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_helix_package(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.helix_package.v1"
    assert payload["command_count"] == len(records)
    assert (tmp_path / "bin" / "mekong-helix").exists()
    assert (tmp_path / "config.toml").exists()
    manifest = json.loads((tmp_path / "data" / "helix.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "mekong.command_fabric.adapter.helix.v1"


def test_materialize_helix_package_default(tmp_path) -> None:
    payload = materialize_helix_package(tmp_path)

    assert payload["artifact_count"] == 6
    assert (tmp_path / "README.md").exists()

