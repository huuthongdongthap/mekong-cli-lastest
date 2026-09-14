import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.package_managers import (
    PACKAGE_MANAGER_TARGETS,
    materialize_package_manager_metadata,
)


def test_package_manager_metadata_materializes_global_cli_targets(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_package_manager_metadata(tmp_path, records)

    assert payload["schema"] == "mekong.command_fabric.package_managers.v1"
    assert payload["command_count"] == len(records)
    assert payload["target_count"] == len(PACKAGE_MANAGER_TARGETS)
    assert set(payload["targets"]) == set(PACKAGE_MANAGER_TARGETS)
    assert (tmp_path / "package-managers.json").exists()
    assert (tmp_path / "homebrew" / "mekong-cli.rb").exists()
    assert (tmp_path / "scoop" / "mekong-cli.json").exists()
    assert (tmp_path / "winget" / "Mekong.MekongCLI.yaml").exists()
    assert (tmp_path / "chocolatey" / "mekong-cli.nuspec").exists()
    assert (tmp_path / "npm" / "package.json").exists()
    assert (tmp_path / "npm" / "bin" / "mekong.js").exists()
    assert (tmp_path / "bun" / "package.json").exists()
    assert (tmp_path / "bun" / "bin" / "mekong.js").exists()
    assert (tmp_path / "deno" / "deno.json").exists()
    assert (tmp_path / "deno" / "mekong.ts").exists()
    assert (tmp_path / "asdf" / "README.md").exists()
    assert (tmp_path / "asdf" / "bin" / "list-all").exists()
    assert (tmp_path / "asdf" / "bin" / "download").exists()
    assert (tmp_path / "asdf" / "bin" / "install").exists()
    assert (tmp_path / "mise" / "mise.toml").exists()
    assert (tmp_path / "aqua" / "registry.yaml").exists()
    assert (tmp_path / "pkgx" / "package.yml").exists()
    assert (tmp_path / "snap" / "snapcraft.yaml").exists()
    assert (tmp_path / "flatpak" / "io.mekongmind.MekongCLI.yaml").exists()
    assert (tmp_path / "appimage" / "AppRun").exists()
    assert (tmp_path / "appimage" / "mekong-cli.desktop").exists()
    assert (tmp_path / "appimage" / "README.md").exists()
    assert (tmp_path / "freebsd" / "Makefile").exists()
    assert (tmp_path / "openbsd" / "Makefile").exists()
    assert (tmp_path / "netbsd" / "Makefile").exists()
    assert (tmp_path / "pypi" / "pyproject.toml").exists()
    assert (tmp_path / "nix" / "flake.nix").exists()
    assert (tmp_path / "aur" / "PKGBUILD").exists()
    assert (tmp_path / "debian" / "control").exists()
    assert (tmp_path / "rpm" / "mekong-cli.spec").exists()
    assert (tmp_path / "docker" / "Dockerfile").exists()
    assert f"Mekong command fabric CLI with {len(records)} command definitions" in (
        tmp_path / "homebrew" / "mekong-cli.rb"
    ).read_text(encoding="utf-8")
    assert 'system "#{bin}/mekong", "--help"' in (tmp_path / "homebrew" / "mekong-cli.rb").read_text(
        encoding="utf-8"
    )
    assert 'license "BSL-1.1"' in (tmp_path / "homebrew" / "mekong-cli.rb").read_text(encoding="utf-8")
    assert 'depends_on "python@3.12"' in (tmp_path / "homebrew" / "mekong-cli.rb").read_text(
        encoding="utf-8"
    )
    assert '"license": "BSL-1.1"' in (tmp_path / "scoop" / "mekong-cli.json").read_text(encoding="utf-8")
    assert "License: BSL-1.1" in (tmp_path / "winget" / "Mekong.MekongCLI.yaml").read_text(
        encoding="utf-8"
    )
    npm_metadata = json.loads((tmp_path / "npm" / "package.json").read_text(encoding="utf-8"))
    npm_bin = (tmp_path / "npm" / "bin" / "mekong.js").read_text(encoding="utf-8")
    assert npm_metadata["name"] == "mekong-cli"
    assert npm_metadata["license"] == "BSL-1.1"
    assert npm_metadata["bin"]["mekong"] == "bin/mekong.js"
    assert "python3', ['-m', 'src.main'" in npm_bin
    assert (tmp_path / "npm" / "bin" / "mekong.js").stat().st_mode & 0o111
    bun_metadata = json.loads((tmp_path / "bun" / "package.json").read_text(encoding="utf-8"))
    bun_bin = (tmp_path / "bun" / "bin" / "mekong.js").read_text(encoding="utf-8")
    deno_metadata = json.loads((tmp_path / "deno" / "deno.json").read_text(encoding="utf-8"))
    deno_bin = (tmp_path / "deno" / "mekong.ts").read_text(encoding="utf-8")
    assert bun_metadata["license"] == "BSL-1.1"
    assert bun_metadata["bin"]["mekong"] == "bin/mekong.js"
    assert "python3', ['-m', 'src.main'" in bun_bin
    assert (tmp_path / "bun" / "bin" / "mekong.js").stat().st_mode & 0o111
    assert deno_metadata["license"] == "BSL-1.1"
    assert "deno install --global --allow-run --allow-read --name mekong ./mekong.ts" in json.dumps(
        deno_metadata
    )
    assert "new Deno.Command('python3'" in deno_bin
    assert "'-m', 'src.main'" in deno_bin
    asdf_readme = (tmp_path / "asdf" / "README.md").read_text(encoding="utf-8")
    asdf_list_all = (tmp_path / "asdf" / "bin" / "list-all").read_text(encoding="utf-8")
    asdf_download = (tmp_path / "asdf" / "bin" / "download").read_text(encoding="utf-8")
    asdf_install = (tmp_path / "asdf" / "bin" / "install").read_text(encoding="utf-8")
    mise_metadata = (tmp_path / "mise" / "mise.toml").read_text(encoding="utf-8")
    assert "asdf plugin add mekong" in asdf_readme
    assert "git ls-remote --tags" in asdf_list_all
    assert "curl -fsSL" in asdf_download
    assert "python3 -m pip install" in asdf_install
    assert (tmp_path / "asdf" / "bin" / "list-all").stat().st_mode & 0o111
    assert (tmp_path / "asdf" / "bin" / "download").stat().st_mode & 0o111
    assert (tmp_path / "asdf" / "bin" / "install").stat().st_mode & 0o111
    assert '"github:longtho638-jpg/mekong-cli" = "latest"' in mise_metadata
    aqua_metadata = (tmp_path / "aqua" / "registry.yaml").read_text(encoding="utf-8")
    pkgx_metadata = (tmp_path / "pkgx" / "package.yml").read_text(encoding="utf-8")
    assert "type: github_release" in aqua_metadata
    assert "repo_name: mekong-cli" in aqua_metadata
    assert "github: longtho638-jpg/mekong-cli" in pkgx_metadata
    assert "provides:" in pkgx_metadata
    snap_metadata = (tmp_path / "snap" / "snapcraft.yaml").read_text(encoding="utf-8")
    flatpak_metadata = (tmp_path / "flatpak" / "io.mekongmind.MekongCLI.yaml").read_text(
        encoding="utf-8"
    )
    appimage_apprun = (tmp_path / "appimage" / "AppRun").read_text(encoding="utf-8")
    appimage_desktop = (tmp_path / "appimage" / "mekong-cli.desktop").read_text(encoding="utf-8")
    assert "apps:" in snap_metadata
    assert "command: bin/mekong" in snap_metadata
    assert "app-id: io.mekongmind.MekongCLI" in flatpak_metadata
    assert "command: mekong" in flatpak_metadata
    assert 'exec "${APPDIR}/usr/bin/mekong" "$@"' in appimage_apprun
    assert "Terminal=true" in appimage_desktop
    assert (tmp_path / "appimage" / "AppRun").stat().st_mode & 0o111
    freebsd_metadata = (tmp_path / "freebsd" / "Makefile").read_text(encoding="utf-8")
    openbsd_metadata = (tmp_path / "openbsd" / "Makefile").read_text(encoding="utf-8")
    netbsd_metadata = (tmp_path / "netbsd" / "Makefile").read_text(encoding="utf-8")
    assert "PORTNAME=\tmekong-cli" in freebsd_metadata
    assert "USE_PYTHON=\tautoplist pep517" in freebsd_metadata
    assert "DISTNAME =\tmekong-cli-0.0.0" in openbsd_metadata
    assert "PERMIT_PACKAGE =\tYes" in openbsd_metadata
    assert "DISTNAME=\tmekong-cli-0.0.0" in netbsd_metadata
    assert '.include "../../mk/bsd.pkg.mk"' in netbsd_metadata
    pypi_metadata = (tmp_path / "pypi" / "pyproject.toml").read_text(encoding="utf-8")
    docker_metadata = (tmp_path / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.9,<3.13"' in pypi_metadata
    assert 'license = { text = "BSL-1.1" }' in pypi_metadata
    assert 'mekong = "src.main:app"' in pypi_metadata
    assert "pkgs.python312Packages.buildPythonApplication" in (tmp_path / "nix" / "flake.nix").read_text(
        encoding="utf-8"
    )
    assert "license=('BSL-1.1')" in (tmp_path / "aur" / "PKGBUILD").read_text(encoding="utf-8")
    assert "License:        BSL-1.1" in (tmp_path / "rpm" / "mekong-cli.spec").read_text(
        encoding="utf-8"
    )
    assert "FROM python:3.12-slim" in docker_metadata
    assert 'ENTRYPOINT ["mekong"]' in docker_metadata


def test_package_manager_metadata_default(tmp_path) -> None:
    payload = materialize_package_manager_metadata(tmp_path)

    assert payload["schema"] == "mekong.command_fabric.package_managers.v1"
    assert payload["target_count"] == len(PACKAGE_MANAGER_TARGETS)
    assert (tmp_path / "package-managers.json").exists()
