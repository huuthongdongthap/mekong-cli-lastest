import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.workspace_templates import materialize_workspace_templates


def test_workspace_templates_materialize_cloud_ide_bootstrap(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_workspace_templates(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.workspace_templates.v1"
    assert payload["command_count"] == len(records)
    assert payload["artifact_count"] == 3
    devcontainer = json.loads((tmp_path / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8"))
    gitpod = (tmp_path / ".gitpod.yml").read_text(encoding="utf-8")
    codespaces = (tmp_path / "codespaces" / "README.md").read_text(encoding="utf-8")
    assert devcontainer["image"] == "mcr.microsoft.com/devcontainers/python:3.12"
    assert "command-fabric export --scope project" in devcontainer["postCreateCommand"]
    assert "python3 -m pip install -e ." in gitpod
    assert "GitHub Codespaces" in codespaces
