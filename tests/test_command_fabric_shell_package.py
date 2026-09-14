from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.shell_package import (
    bash_completion,
    elvish_completion,
    fish_completion,
    materialize_shell_completion,
    nushell_completion,
    powershell_completion,
    zsh_completion,
)


def test_shell_completion_scripts_include_known_commands() -> None:
    records = build_command_catalog()

    assert "complete -F _mekong_completions mekong" in bash_completion(records)
    assert "cook" in bash_completion(records)
    assert "#compdef mekong" in zsh_completion(records)
    assert "'cook:" in zsh_completion(records)
    assert "complete -c mekong" in fish_completion(records)
    assert "-a 'cook'" in fish_completion(records)
    assert "Register-ArgumentCompleter" in powershell_completion(records)
    assert "'cook'" in powershell_completion(records)
    assert 'def mekong_commands []' in nushell_completion(records)
    assert 'value: "cook"' in nushell_completion(records)
    assert "set edit:completion:arg-completer[mekong]" in elvish_completion(records)
    assert "put cook" in elvish_completion(records)


def test_shell_completion_materializes_all_shells(tmp_path) -> None:
    payload = materialize_shell_completion(tmp_path, build_command_catalog())
    root = tmp_path / "shell"

    assert payload["schema"] == "mekong.command_fabric.shell_completion.v1"
    assert payload["command_count"] == len(build_command_catalog())
    assert (root / "bash" / "mekong.bash").exists()
    assert (root / "zsh" / "_mekong").exists()
    assert (root / "fish" / "mekong.fish").exists()
    assert (root / "powershell" / "mekong.ps1").exists()
    assert (root / "nushell" / "mekong.nu").exists()
    assert (root / "elvish" / "mekong.elv").exists()
    assert (root / "install.sh").exists()
    installer = (root / "install.sh").read_text(encoding="utf-8")
    assert "printf '%s\\n'" in installer
    assert "mekong.ps1" in installer
    assert "mekong.nu" in installer
    assert "mekong.elv" in installer


def test_shell_completion_materializes_all_shells_default(tmp_path) -> None:
    payload = materialize_shell_completion(tmp_path)

    assert payload["schema"] == "mekong.command_fabric.shell_completion.v1"
    assert payload["host"] == "shell"
    assert payload["command_count"] == len(build_command_catalog())
    assert (tmp_path / "shell" / "bash" / "mekong.bash").exists()
