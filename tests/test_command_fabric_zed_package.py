import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.zed_package import extension_toml, lib_rs, materialize_zed_package


def test_zed_manifest_declares_context_server() -> None:
    manifest = extension_toml()

    assert 'id = "mekong-command-fabric"' in manifest
    assert "[context_servers.mekong-command-fabric]" in manifest


def test_zed_extension_entrypoint_returns_mcp_command() -> None:
    source = lib_rs(build_command_catalog())

    assert "context_server_command" in source
    assert "mekong-command-fabric-mcp" in source


def test_zed_package_materializes_extension_scaffold(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_zed_package(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.zed_package.v1"
    assert payload["command_count"] == len(records)
    assert (tmp_path / "extension.toml").exists()
    assert (tmp_path / "src" / "lib.rs").exists()
    manifest = json.loads((tmp_path / "data" / "zed.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "mekong.command_fabric.adapter.zed.v1"


def test_zed_package_materializes_default(tmp_path) -> None:
    payload = materialize_zed_package(tmp_path)

    assert payload["schema"] == "mekong.command_fabric.zed_package.v1"
    assert payload["artifact_count"] == 6
    assert (tmp_path / "Cargo.toml").exists()
    assert payload["command_count"] == len(build_command_catalog())
