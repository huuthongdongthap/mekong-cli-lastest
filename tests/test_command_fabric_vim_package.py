import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.vim_package import materialize_vim_package, plugin_vimscript


def test_vim_plugin_registers_mekong_command() -> None:
    source = plugin_vimscript(build_command_catalog())

    assert "command! -nargs=+" in source
    assert "Mekong" in source
    assert "MekongBuildInvocation" in source
    assert "shellescape(l:part)" in source
    assert "terminal " in source


def test_vim_package_materializes_plugin(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_vim_package(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.vim_package.v1"
    assert payload["command_count"] == len(records)
    assert (tmp_path / "plugin" / "mekong_command_fabric.vim").exists()
    assert (tmp_path / "data" / "vim.json").exists()
    manifest = json.loads((tmp_path / "data" / "vim.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "mekong.command_fabric.adapter.vim.v1"


def test_vim_package_materializes_default(tmp_path) -> None:
    payload = materialize_vim_package(tmp_path)

    assert payload["schema"] == "mekong.command_fabric.vim_package.v1"
    assert payload["artifact_count"] == 5
    assert (tmp_path / "README.md").exists()
    assert payload["command_count"] == len(build_command_catalog())
