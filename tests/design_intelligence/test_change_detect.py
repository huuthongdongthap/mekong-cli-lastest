# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Tests for change detection + the opt-in design-audit gate hook."""

from __future__ import annotations

from unittest.mock import patch

from src.design_intelligence.change_detect import (
    ChangeClass,
    changed_files,
    classify,
    should_trigger_design_audit,
)


# ------------------------------------------------------------------ classify
def test_html_triggers_frontend() -> None:
    assert classify(["index.html"]) is ChangeClass.FRONTEND


def test_jsx_tsx_css_trigger_frontend() -> None:
    assert classify(["src/app/page.tsx"]) is ChangeClass.FRONTEND
    assert classify(["components/Hero.jsx"]) is ChangeClass.FRONTEND
    assert classify(["styles/main.css"]) is ChangeClass.FRONTEND


def test_tailwind_and_tokens_trigger_frontend() -> None:
    assert classify(["tailwind.config.ts"]) is ChangeClass.FRONTEND
    assert classify(["design.tokens.json"]) is ChangeClass.FRONTEND
    assert classify(["src/tokens.css"]) is ChangeClass.FRONTEND


def test_pages_layouts_routes_dirs_trigger_frontend() -> None:
    assert classify(["pages/about.tsx"]) is ChangeClass.FRONTEND
    assert classify(["layouts/base.html"]) is ChangeClass.FRONTEND
    assert classify(["routes/home.tsx"]) is ChangeClass.FRONTEND


def test_backend_only_python_skips() -> None:
    assert classify(["src/core/billing.py"]) is ChangeClass.BACKEND_ONLY
    assert should_trigger_design_audit(["src/core/billing.py"]) is False


def test_migration_only_skips() -> None:
    assert classify(["migrations/0001_init.py"]) is ChangeClass.BACKEND_ONLY
    assert should_trigger_design_audit(["migrations/0001_init.py"]) is False


def test_cli_only_skips() -> None:
    assert classify(["src/cli/ui_commands.py"]) is ChangeClass.BACKEND_ONLY
    assert should_trigger_design_audit(["src/cli/ui_commands.py"]) is False


def test_infra_only_skips() -> None:
    assert classify([".github/workflows/gates.yml"]) is ChangeClass.BACKEND_ONLY
    assert classify(["Dockerfile"]) is ChangeClass.BACKEND_ONLY
    assert should_trigger_design_audit(["Dockerfile"]) is False


def test_mixed_diff_frontend_wins() -> None:
    paths = ["src/core/billing.py", "src/app/page.tsx"]
    assert classify(paths) is ChangeClass.FRONTEND
    assert should_trigger_design_audit(paths) is True


def test_empty_diff_skips() -> None:
    assert classify([]) is ChangeClass.EMPTY
    assert should_trigger_design_audit([]) is False


# ------------------------------------------------------------------ git helper
def test_changed_files_returns_list_from_git() -> None:
    fake = "src/app/page.tsx\nsrc/core/billing.py\n"
    with patch("src.design_intelligence.change_detect.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = fake
        assert changed_files() == ["src/app/page.tsx", "src/core/billing.py"]


def test_changed_files_empty_when_git_missing() -> None:
    with patch(
        "src.design_intelligence.change_detect.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        assert changed_files() == []


def test_changed_files_empty_on_git_error() -> None:
    with patch("src.design_intelligence.change_detect.subprocess.run") as run:
        run.return_value.returncode = 128
        run.return_value.stdout = ""
        assert changed_files() == []


# ------------------------------------------------------------------ gate hook
def test_suggest_design_audit_triggers_on_frontend_diff() -> None:
    with patch("src.cli.sdlc.gate_check.changed_files", return_value=["src/app/page.tsx"]):
        from src.cli.sdlc.gate_check import suggest_design_audit

        assert suggest_design_audit() is True


def test_suggest_design_audit_skips_backend_diff() -> None:
    with patch("src.cli.sdlc.gate_check.changed_files", return_value=["src/core/billing.py"]):
        from src.cli.sdlc.gate_check import suggest_design_audit

        assert suggest_design_audit() is False
