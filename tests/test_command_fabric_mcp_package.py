from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.mcp_package import materialize_mcp_package, package_json


def test_mcp_package_metadata_exposes_bin() -> None:
    payload = package_json()

    assert payload["name"] == "@mekongcli/command-fabric-mcp"
    assert payload["bin"]["mekong-command-fabric-mcp"] == "./dist/server.js"


def test_mcp_package_materializes_stdio_server(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_mcp_package(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.mcp_package.v1"
    assert payload["command_count"] == len(records)
    assert (tmp_path / "src" / "server.ts").exists()
    assert (tmp_path / "data" / "mcp.json").exists()
    server = (tmp_path / "src" / "server.ts").read_text(encoding="utf-8")
    assert "tools/list" in server
    assert "tools/call" in server


def test_materialize_mcp_package_default(tmp_path) -> None:
    payload = materialize_mcp_package(tmp_path)

    assert payload["artifact_count"] == 6
    assert (tmp_path / "package.json").exists()

