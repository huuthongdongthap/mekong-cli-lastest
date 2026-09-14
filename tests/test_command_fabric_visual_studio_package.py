import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.visual_studio_package import (
    materialize_visual_studio_package,
    package_cs,
    vsix_manifest,
)


def test_visual_studio_vsix_manifest_declares_package() -> None:
    source = vsix_manifest()

    assert "<PackageManifest" in source
    assert "Mekong Command Fabric" in source
    assert "Microsoft.VisualStudio.Community" in source


def test_visual_studio_package_entrypoint_contains_runner() -> None:
    source = package_cs(build_command_catalog())

    assert "MekongCommandFabricPackage" in source
    assert "Process.Start" in source
    assert "BuildArgv" in source
    assert '"/bin/sh"' not in source
    assert '"-lc"' not in source
    assert '"cook"' in source


def test_visual_studio_package_materializes_vsix_scaffold(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_visual_studio_package(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.visual_studio_package.v1"
    assert payload["command_count"] == len(records)
    assert (tmp_path / "source.extension.vsixmanifest").exists()
    assert (tmp_path / "Mekong.CommandFabric.VisualStudio.csproj").exists()
    manifest = json.loads((tmp_path / "data" / "visual-studio.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "mekong.command_fabric.adapter.visual-studio.v1"


def test_visual_studio_package_materializes_default(tmp_path) -> None:
    payload = materialize_visual_studio_package(tmp_path)

    assert payload["schema"] == "mekong.command_fabric.visual_studio_package.v1"
    assert payload["artifact_count"] == 7
    assert (tmp_path / "README.md").exists()
    assert payload["command_count"] == len(build_command_catalog())
