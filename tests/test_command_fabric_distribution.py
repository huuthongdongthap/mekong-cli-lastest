import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.distribution import (
    marketplace_manifest,
    materialize_marketplace_metadata,
)
from src.command_fabric.target_matrix import (
    EXPECTED_MARKETPLACE_TARGET_COUNT,
    EXPECTED_NATIVE_INSTALL_HOST_COUNT,
    EXPECTED_PACKAGE_BUILD_CHECKS,
    EXPECTED_PACKAGE_MANAGER_TARGET_COUNT,
    EXPECTED_RELEASE_SECTION_COUNT,
    EXPECTED_MARKETPLACE_TARGETS,
    target_matrix_summary,
)


def test_marketplace_manifest_covers_global_distribution_targets() -> None:
    records = build_command_catalog()
    payload = marketplace_manifest(records)

    assert payload["schema"] == "mekong.command_fabric.marketplace.v1"
    assert payload["command_count"] == len(records)
    hosts = {target["host"] for target in payload["targets"]}
    assert hosts == EXPECTED_MARKETPLACE_TARGETS


def test_target_matrix_summary_reports_current_surface_counts() -> None:
    payload = target_matrix_summary()

    assert payload["schema"] == "mekong.command_fabric.target_matrix.v1"
    assert payload["marketplace_target_count"] == EXPECTED_MARKETPLACE_TARGET_COUNT
    assert payload["native_install_host_count"] == EXPECTED_NATIVE_INSTALL_HOST_COUNT
    assert payload["package_manager_target_count"] == EXPECTED_PACKAGE_MANAGER_TARGET_COUNT
    assert payload["release_section_count"] == EXPECTED_RELEASE_SECTION_COUNT
    assert payload["package_build_check_count"] == EXPECTED_PACKAGE_BUILD_CHECKS


def test_target_matrix_summary_structure() -> None:
    payload = target_matrix_summary()

    assert payload["schema"] == "mekong.command_fabric.target_matrix.v1"
    assert payload["marketplace_target_count"] == EXPECTED_MARKETPLACE_TARGET_COUNT
    assert "vscode" in payload["ide_targets"]
    assert "claude-code" in payload["agent_cli_targets"]
    assert "docker" in payload["package_manager_targets"]


def test_marketplace_metadata_materializes_manifest(tmp_path) -> None:
    payload = materialize_marketplace_metadata(tmp_path, build_command_catalog())

    assert payload["schema"] == "mekong.command_fabric.marketplace.materialized.v1"
    assert payload["target_count"] == EXPECTED_MARKETPLACE_TARGET_COUNT
    manifest = json.loads((tmp_path / "marketplace.json").read_text(encoding="utf-8"))
    assert manifest["targets"][0]["host"] == "vscode"


def test_marketplace_metadata_materializes_manifest_default(tmp_path) -> None:
    payload = materialize_marketplace_metadata(tmp_path)

    assert payload["target_count"] == EXPECTED_MARKETPLACE_TARGET_COUNT
    assert (tmp_path / "marketplace.json").exists()

