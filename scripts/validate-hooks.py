#!/usr/bin/env python3
"""Validate that every hook wired in ~/.claude/settings.json resolves to a real file.

Usage: python3 scripts/validate-hooks.py [--settings PATH] [--project-root PATH]
Exit 0 = all hooks resolve; exit 1 with list of missing files otherwise.
"""
import argparse
import json
import os
import re
import sys

DEFAULT_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def extract_hook_paths(command: str):
    """Yield filesystem paths referenced by a hook command string."""
    # $CLAUDE_PROJECT_DIR-relative, possibly split across quotes
    for mt in re.finditer(
        r'["\']?\$CLAUDE_PROJECT_DIR["\']?(/[^\s"\']+?\.(?:cjs|mjs|js|sh|py))', command
    ):
        yield ("project", mt.group(1))
    for part in command.split():
        p = part.strip("\"'")
        if p.startswith("/") and re.search(r"\.(cjs|mjs|js|sh|py)$", p):
            yield ("absolute", p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", default=os.path.expanduser("~/.claude/settings.json"))
    ap.add_argument("--project-root", default=DEFAULT_PROJECT_ROOT)
    args = ap.parse_args()

    settings = json.load(open(args.settings))
    missing = []
    total = 0

    for event, entries in settings.get("hooks", {}).items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                for kind, ref in extract_hook_paths(cmd):
                    total += 1
                    path = (
                        os.path.join(args.project_root, ref.lstrip("/"))
                        if kind == "project"
                        else ref
                    )
                    if not os.path.exists(path):
                        missing.append((event, cmd.strip()[:90], path))

    print(f"hooks checked: {total}")
    if missing:
        print(f"MISSING ({len(missing)}):", file=sys.stderr)
        for ev, cmd, path in missing:
            print(f"  [{ev}] {path}\n          from: {cmd}", file=sys.stderr)
        return 1
    print("all hook files resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
