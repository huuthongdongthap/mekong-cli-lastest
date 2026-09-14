from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.release_bundle import materialize_release_bundle
from src.command_fabric.target_matrix import (
    EXPECTED_RELEASE_SECTION_COUNT,
    REQUIRED_RELEASE_SECTIONS,
)


def test_release_bundle_materializes_all_portability_surfaces(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_release_bundle(tmp_path, scope="project")

    assert payload["schema"] == "mekong.command_fabric.release_bundle.v1"
    assert payload["command_count"] == len(records)
    assert payload["section_count"] == EXPECTED_RELEASE_SECTION_COUNT
    section_names = {section["name"] for section in payload["sections"]}
    assert section_names == REQUIRED_RELEASE_SECTIONS
    assert (tmp_path / "manifests" / "canonical.json").exists()
    assert (tmp_path / "manifests" / "adapters.json").exists()
    assert (tmp_path / "ide-extensions" / "vscode" / "package.json").exists()
    assert (tmp_path / "ide-extensions" / "cursor" / "src" / "extension.ts").exists()
    assert (tmp_path / "ide-extensions" / "windsurf" / "src" / "extension.ts").exists()
    assert (tmp_path / "ide-extensions" / "theia" / "src" / "extension.ts").exists()
    assert (
        tmp_path
        / "ide-extensions"
        / "jetbrains"
        / "src"
        / "main"
        / "resources"
        / "META-INF"
        / "plugin.xml"
    ).exists()
    assert (tmp_path / "shell-completion" / "shell" / "zsh" / "_mekong").exists()
    assert (tmp_path / "shell-completion" / "shell" / "powershell" / "mekong.ps1").exists()
    assert (tmp_path / "shell-completion" / "shell" / "nushell" / "mekong.nu").exists()
    assert (tmp_path / "shell-completion" / "shell" / "elvish" / "mekong.elv").exists()
    assert (tmp_path / "agent-cli" / "claude-code" / "commands" / "cook.md").exists()
    assert (tmp_path / "agent-cli" / "codex" / "manifest.json").exists()
    assert (tmp_path / "agent-cli" / "cursor-agent" / "manifest.json").exists()
    assert (tmp_path / "agent-cli" / "amp" / "manifest.json").exists()
    assert (tmp_path / "agent-cli" / "goose" / "manifest.json").exists()
    assert (tmp_path / "agent-cli" / "crush" / "manifest.json").exists()
    assert (tmp_path / "agent-cli" / "kiro-cli" / "manifest.json").exists()
    assert (tmp_path / "contracts" / "contracts" / "commands" / "cook.json").exists()
    assert (tmp_path / "marketplace" / "marketplace.json").exists()
    assert (tmp_path / "package-managers" / "homebrew" / "mekong-cli.rb").exists()
    assert (tmp_path / "package-managers" / "scoop" / "mekong-cli.json").exists()
    assert (tmp_path / "package-managers" / "winget" / "Mekong.MekongCLI.yaml").exists()
    assert (tmp_path / "package-managers" / "chocolatey" / "mekong-cli.nuspec").exists()
    assert (tmp_path / "package-managers" / "npm" / "package.json").exists()
    assert (tmp_path / "package-managers" / "npm" / "bin" / "mekong.js").exists()
    assert (tmp_path / "package-managers" / "bun" / "package.json").exists()
    assert (tmp_path / "package-managers" / "bun" / "bin" / "mekong.js").exists()
    assert (tmp_path / "package-managers" / "deno" / "deno.json").exists()
    assert (tmp_path / "package-managers" / "deno" / "mekong.ts").exists()
    assert (tmp_path / "package-managers" / "asdf" / "README.md").exists()
    assert (tmp_path / "package-managers" / "asdf" / "bin" / "install").exists()
    assert (tmp_path / "package-managers" / "mise" / "mise.toml").exists()
    assert (tmp_path / "package-managers" / "aqua" / "registry.yaml").exists()
    assert (tmp_path / "package-managers" / "pkgx" / "package.yml").exists()
    assert (tmp_path / "package-managers" / "snap" / "snapcraft.yaml").exists()
    assert (tmp_path / "package-managers" / "flatpak" / "io.mekongmind.MekongCLI.yaml").exists()
    assert (tmp_path / "package-managers" / "appimage" / "AppRun").exists()
    assert (tmp_path / "package-managers" / "freebsd" / "Makefile").exists()
    assert (tmp_path / "package-managers" / "openbsd" / "Makefile").exists()
    assert (tmp_path / "package-managers" / "netbsd" / "Makefile").exists()
    assert (tmp_path / "package-managers" / "pypi" / "pyproject.toml").exists()
    assert (tmp_path / "package-managers" / "nix" / "flake.nix").exists()
    assert (tmp_path / "package-managers" / "aur" / "PKGBUILD").exists()
    assert (tmp_path / "package-managers" / "debian" / "control").exists()
    assert (tmp_path / "package-managers" / "rpm" / "mekong-cli.spec").exists()
    assert (tmp_path / "package-managers" / "docker" / "Dockerfile").exists()
    assert (tmp_path / "workspace-templates" / ".devcontainer" / "devcontainer.json").exists()
    assert (tmp_path / "workspace-templates" / ".gitpod.yml").exists()
    assert (tmp_path / "workspace-templates" / "codespaces" / "README.md").exists()
    assert (tmp_path / "npm-package" / "package.json").exists()
    assert (tmp_path / "npm-package" / "data" / "adapters.json").exists()
    assert (tmp_path / "mcp-package" / "src" / "server.ts").exists()
    assert (tmp_path / "visual-studio-package" / "source.extension.vsixmanifest").exists()
    assert (tmp_path / "eclipse-package" / "plugin.xml").exists()
    assert (tmp_path / "fleet-package" / "plugin.json").exists()
    assert (tmp_path / "nova-package" / "extension.js").exists()
    assert (tmp_path / "lapce-package" / "lapce-plugin.toml").exists()
    assert (tmp_path / "kakoune-package" / "kakrc").exists()
    assert (tmp_path / "micro-package" / "mekong.lua").exists()
    assert (tmp_path / "vim-package" / "plugin" / "mekong_command_fabric.vim").exists()
    assert (tmp_path / "neovim-package" / "lua" / "mekong.lua").exists()
    assert (tmp_path / "helix-package" / "bin" / "mekong-helix").exists()
    assert (tmp_path / "zed-package" / "extension.toml").exists()
    assert (tmp_path / "emacs-package" / "mekong-command-fabric.el").exists()
    assert (tmp_path / "sublime-package" / "mekong_command_fabric.py").exists()


def test_release_bundle_supports_host_selection(tmp_path) -> None:
    payload = materialize_release_bundle(
        tmp_path,
        scope="project",
        ide_hosts=["vscode"],
        agent_hosts=["codex"],
    )

    section_names = {section["name"] for section in payload["sections"]}
    assert "ide-vscode" in section_names
    assert "ide-cursor" not in section_names
    assert (tmp_path / "agent-cli" / "codex" / "README.md").exists()
    assert not (tmp_path / "agent-cli" / "claude-code").exists()
