#!/usr/bin/env python3
"""Add /tui command to entrypoint.py"""
import os
import re

_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
target = os.path.join(_repo_root, "cli", "entrypoint.py")
content = open(target).read()

# 1. Add import after palette_app import
old_import = "from cli.tui.palette import palette_app # noqa: E402"
new_import = """from cli.tui.palette import palette_app # noqa: E402
from cli.tui.tmux_launcher import TmuxLauncher, TmuxLayout # noqa: E402"""
content = content.replace(old_import, new_import)

# 2. Add /tui command after the last app.command() block
tui_command = '''

@app.command(name="tui")
def tui_cmd(
    initial_cmd: str = typer.Argument("", help="Initial command to run (optional)"),
    single_pane: bool = typer.Option(False, "--single-pane", help="Force single-pane mode (no tmux)"),
) -> None:
    """🖥️ TUI Mode — Warp-style interactive terminal with command palette + block output."""
    launcher = TmuxLauncher()
    if single_pane or not launcher.is_available():
        launcher._fallback(initial_cmd)
        return
    launcher.launch(initial_cmd)
'''

# Insert after the last top-level command (`scaffold_cmd`), before `def main():`
marker = "\ndef main():"
if marker in content and "def tui_cmd" not in content:
    content = content.replace(marker, tui_command + "\n" + marker)
    with open(target, "w") as f:
        f.write(content)
    print(f"OK: Added /tui command ({len(content)} bytes)")
else:
    print(f"SKIP: marker={marker in content}, already_has_tui={'def tui_cmd' in content}")
