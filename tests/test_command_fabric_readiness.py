from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.readiness import audit_universal_readiness


def test_universal_readiness_audit_passes_for_project_scope(tmp_path) -> None:
    payload = audit_universal_readiness(tmp_path / "out", tmp_path / "home", scope="project")

    assert payload["schema"] == "mekong.command_fabric.universal_readiness.v1"
    assert payload["ready"] is True
    assert payload["command_count"] == len(build_command_catalog())
    checks = {check["id"]: check for check in payload["checks"]}
    assert checks["required-sections"]["passed"] is True
    assert checks["native-install-hosts"]["passed"] is True
    assert checks["package-manager-targets"]["passed"] is True


def test_universal_readiness_audit_passes_for_global_scope(tmp_path) -> None:
    payload = audit_universal_readiness(tmp_path / "out", tmp_path / "home", scope="global")

    assert payload["ready"] is True
    assert payload["command_count"] > 91
    checks = {check["id"]: check for check in payload["checks"]}
    assert checks["npm-scope"]["evidence"] == "global"
    assert checks["npm-command-count"]["passed"] is True
    assert checks["visual-studio-command-count"]["passed"] is True
    assert checks["eclipse-command-count"]["passed"] is True
    assert checks["fleet-command-count"]["passed"] is True
    assert checks["nova-command-count"]["passed"] is True
    assert checks["lapce-command-count"]["passed"] is True
    assert checks["kakoune-command-count"]["passed"] is True
    assert checks["micro-command-count"]["passed"] is True
    assert checks["vim-command-count"]["passed"] is True
    assert checks["neovim-command-count"]["passed"] is True
    assert checks["helix-command-count"]["passed"] is True
    assert checks["zed-command-count"]["passed"] is True
    assert checks["emacs-command-count"]["passed"] is True
    assert checks["sublime-command-count"]["passed"] is True
    assert checks["package-manager-targets"]["evidence"] == "23 targets"


def test_universal_readiness_audit_passes_default(tmp_path) -> None:
    payload = audit_universal_readiness(
        tmp_path / "out",
        tmp_path / "home",
        scope="project",
    )

    assert payload["schema"] == "mekong.command_fabric.universal_readiness.v1"
    assert payload["ready"] is True
