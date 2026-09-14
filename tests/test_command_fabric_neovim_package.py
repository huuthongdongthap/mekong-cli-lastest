import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.neovim_package import materialize_neovim_package, plugin_lua


def test_neovim_plugin_registers_mekong_user_command() -> None:
    source = plugin_lua(build_command_catalog())

    assert "vim.api.nvim_create_user_command" in source
    assert "Mekong" in source
    assert "build_invocation" in source
    assert "vim.fn.shellescape(part)" in source
    assert "terminal " in source


def test_neovim_package_materializes_lua_plugin(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_neovim_package(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.neovim_package.v1"
    assert payload["command_count"] == len(records)
    assert (tmp_path / "lua" / "mekong.lua").exists()
    assert (tmp_path / "data" / "neovim.json").exists()
    manifest = json.loads((tmp_path / "data" / "neovim.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "mekong.command_fabric.adapter.neovim.v1"


def test_materialize_neovim_package_default(tmp_path) -> None:
    payload = materialize_neovim_package(tmp_path)

    assert payload["artifact_count"] == 5
    assert (tmp_path / "README.md").exists()

