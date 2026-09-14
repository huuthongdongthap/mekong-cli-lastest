from src.command_fabric.native_install import materialize_native_install


def test_native_install_dry_run_reports_targets_without_copying(tmp_path) -> None:
    target_root = tmp_path / "home"
    payload = materialize_native_install(
        tmp_path / "out",
        scope="project",
        hosts=["claude-code", "shell"],
        target_root=target_root,
        dry_run=True,
    )

    assert payload["schema"] == "mekong.command_fabric.native_install.v1"
    assert payload["dry_run"] is True
    assert payload["install_count"] == 2
    targets = {install["host"]: install["target"] for install in payload["installs"]}
    assert targets["claude-code"].endswith(".claude/commands/mekong")
    assert targets["shell"].endswith(".mekong/completions")
    assert not (target_root / ".claude" / "commands" / "mekong").exists()


def test_native_install_write_copies_selected_host_packages(tmp_path) -> None:
    target_root = tmp_path / "home"
    payload = materialize_native_install(
        tmp_path / "out",
        scope="project",
        hosts=["opencode", "codex"],
        target_root=target_root,
        dry_run=False,
    )

    assert payload["dry_run"] is False
    assert all(install["installed"] is True for install in payload["installs"])
    assert (target_root / ".config" / "opencode" / "commands" / "mekong" / "commands" / "cook.md").exists()
    assert (target_root / ".codex" / "command-fabric" / "mekong" / "manifest.json").exists()


def test_native_install_write_copies_cross_shell_completions(tmp_path) -> None:
    target_root = tmp_path / "home"
    payload = materialize_native_install(
        tmp_path / "out",
        scope="project",
        hosts=["shell"],
        target_root=target_root,
        dry_run=False,
    )

    completion_root = target_root / ".mekong" / "completions"
    assert payload["install_count"] == 1
    assert (completion_root / "bash" / "mekong.bash").exists()
    assert (completion_root / "zsh" / "_mekong").exists()
    assert (completion_root / "fish" / "mekong.fish").exists()
    assert (completion_root / "powershell" / "mekong.ps1").exists()
    assert (completion_root / "nushell" / "mekong.nu").exists()
    assert (completion_root / "elvish" / "mekong.elv").exists()


def test_native_install_defaults_to_dry_run(tmp_path) -> None:
    payload = materialize_native_install(
        tmp_path / "out",
        scope="project",
        hosts=["gemini-cli"],
        target_root=tmp_path / "home",
        dry_run=True,
    )

    assert payload["dry_run"] is True
    assert payload["install_count"] == 1
    assert payload["installs"][0]["host"] == "gemini-cli"
    assert not (tmp_path / "home" / ".gemini" / "commands" / "mekong").exists()


def test_native_install_writes_manifest_agent_cli_packages(tmp_path) -> None:
    target_root = tmp_path / "home"
    payload = materialize_native_install(
        tmp_path / "out",
        scope="project",
        hosts=["aider", "continue-dev", "copilot-cli", "cursor-agent", "amp", "goose", "crush", "kiro-cli"],
        target_root=target_root,
        dry_run=False,
    )

    assert payload["install_count"] == 8
    assert (target_root / ".mekong" / "command-fabric" / "aider" / "manifest.json").exists()
    assert (target_root / ".mekong" / "command-fabric" / "continue-dev" / "manifest.json").exists()
    assert (target_root / ".mekong" / "command-fabric" / "copilot-cli" / "manifest.json").exists()
    assert (target_root / ".mekong" / "command-fabric" / "cursor-agent" / "manifest.json").exists()
    assert (target_root / ".mekong" / "command-fabric" / "amp" / "manifest.json").exists()
    assert (target_root / ".mekong" / "command-fabric" / "goose" / "manifest.json").exists()
    assert (target_root / ".mekong" / "command-fabric" / "crush" / "manifest.json").exists()
    assert (target_root / ".mekong" / "command-fabric" / "kiro-cli" / "manifest.json").exists()

