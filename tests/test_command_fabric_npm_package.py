import json

from src.command_fabric.catalog import build_command_catalog, build_global_command_catalog
from src.command_fabric.npm_package import materialize_npm_package, package_json


def test_npm_package_metadata_is_publishable_shape() -> None:
    payload = package_json()

    assert payload["name"] == "@mekongcli/command-fabric"
    assert payload["type"] == "module"
    assert payload["scripts"]["build"] == "tsc -p tsconfig.json"


def test_npm_package_materializes_consumer_package(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_npm_package(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.npm_package.v1"
    assert payload["command_count"] == len(records)
    assert (tmp_path / "package.json").exists()
    assert (tmp_path / "src" / "index.ts").exists()
    assert (tmp_path / "data" / "canonical.json").exists()
    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert package["files"] == ["dist", "data", "README.md"]


def test_materialize_npm_package_default(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_npm_package(tmp_path)

    assert payload["command_count"] == len(records)
    assert (tmp_path / "data" / "mcp.json").exists()


def test_npm_package_global_scope_keeps_data_catalog_in_sync(tmp_path) -> None:
    payload = materialize_npm_package(
        tmp_path,
        build_global_command_catalog(),
        scope="global",
    )

    canonical = json.loads((tmp_path / "data" / "canonical.json").read_text(encoding="utf-8"))
    assert payload["scope"] == "global"
    assert canonical["count"] == payload["command_count"]
    assert canonical["count"] > 91

