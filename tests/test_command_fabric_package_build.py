from src.command_fabric.package_build import verify_package_builds
from src.command_fabric.release_bundle import materialize_release_bundle
from src.command_fabric.target_matrix import EXPECTED_PACKAGE_BUILD_CHECKS, PACKAGE_BUILD_TARGETS


def test_package_build_verifier_checks_generated_ide_scaffolds(tmp_path) -> None:
    materialize_release_bundle(tmp_path, scope="project")
    payload = verify_package_builds(tmp_path)

    assert payload["schema"] == "mekong.command_fabric.package_build.v1"
    assert payload["check_count"] == EXPECTED_PACKAGE_BUILD_CHECKS
    hosts = {check["host"] for check in payload["checks"]}
    assert hosts == set(PACKAGE_BUILD_TARGETS)


def test_package_build_verification_structure(tmp_path) -> None:
    materialize_release_bundle(tmp_path, scope="project")
    payload = verify_package_builds(tmp_path)

    assert payload["check_count"] == EXPECTED_PACKAGE_BUILD_CHECKS
    assert len(payload["checks"]) == EXPECTED_PACKAGE_BUILD_CHECKS
    for check in payload["checks"]:
        assert "host" in check
        assert "package_path" in check
        assert len(check["checks"]) > 0
