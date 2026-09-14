import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.emacs_package import emacs_lisp, materialize_emacs_package


def test_emacs_lisp_defines_interactive_command() -> None:
    source = emacs_lisp(build_command_catalog())

    assert "defun mekong-command-fabric-run" in source
    assert "completing-read" in source
    assert "compile invocation" in source


def test_emacs_package_materializes_elisp_and_adapter_data(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_emacs_package(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.emacs_package.v1"
    assert payload["command_count"] == len(records)
    assert (tmp_path / "mekong-command-fabric.el").exists()
    manifest = json.loads((tmp_path / "data" / "emacs.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "mekong.command_fabric.adapter.emacs.v1"


def test_materialize_emacs_package_default(tmp_path) -> None:
    payload = materialize_emacs_package(tmp_path)

    assert payload["artifact_count"] == 4
    assert (tmp_path / "README.md").exists()

