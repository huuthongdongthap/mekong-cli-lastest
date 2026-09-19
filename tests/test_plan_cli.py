"""Tests for the ``mk plan from-init`` CLI command.

Loads plan_app directly (same pattern as test_company_init_cli).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import plan sub-app directly (matches company_init test pattern)
from src.cli.commands.plan import app as plan_app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(argv: list[str], working_dir: Path, input: str | None = None):
    cwd = os.getcwd()
    os.chdir(working_dir)
    try:
        return runner.invoke(plan_app, argv, input=input)
    finally:
        os.chdir(cwd)


def _init_company(tmp_path: Path, **kwargs) -> None:
    from src.core.company_init import CompanyConfig, init_company

    cfg = CompanyConfig(
        company_name=kwargs.get("company_name", "TestCo"),
        product_type=kwargs.get("product_type", "saas"),
        scenario=kwargs.get("scenario", "hybrid"),
        budget_tier=kwargs.get("budget_tier", "minimal"),
        primary_language=kwargs.get("primary_language", "en"),
    )
    init_company(cfg, base_dir=tmp_path)


# ---------------------------------------------------------------------------
# Contract: preconditions
# ---------------------------------------------------------------------------


class TestPreconditions:
    def test_errors_without_company_json(self, tmp_path: Path) -> None:
        result = _invoke([], tmp_path)
        assert result.exit_code == 1

    def test_error_mentions_init(self, tmp_path: Path) -> None:
        result = _invoke([], tmp_path)
        combined = (result.stdout + (result.stderr or "")).lower()
        assert "company init" in combined or "company.json" in combined


# ---------------------------------------------------------------------------
# Contract: successful run
# ---------------------------------------------------------------------------


class TestSuccessfulRun:
    def test_creates_spec_output(self, tmp_path: Path) -> None:
        _init_company(tmp_path)
        result = _invoke([], tmp_path)
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        assert (tmp_path / ".mekong" / "SPEC_OUTPUT.md").exists()

    def test_creates_plans_directory(self, tmp_path: Path) -> None:
        _init_company(tmp_path)
        _invoke([], tmp_path)
        plans_dir = tmp_path / "plans"
        assert plans_dir.exists()
        assert any(plans_dir.iterdir())

    def test_creates_plan_md(self, tmp_path: Path) -> None:
        _init_company(tmp_path)
        _invoke([], tmp_path)
        plan_dirs = list((tmp_path / "plans").iterdir())
        assert len(plan_dirs) == 1
        assert (plan_dirs[0] / "plan.md").exists()

    def test_plan_md_has_required_sections(self, tmp_path: Path) -> None:
        _init_company(tmp_path)
        _invoke([], tmp_path)
        plan_dirs = list((tmp_path / "plans").iterdir())
        plan_md = (plan_dirs[0] / "plan.md").read_text(encoding="utf-8")
        for keyword in ("Status:", "## Phases", "## Dependencies", "## Acceptance"):
            assert keyword in plan_md, f"Missing '{keyword}' in plan.md"

    def test_plan_directory_naming(self, tmp_path: Path) -> None:
        _init_company(tmp_path, company_name="My Startup")
        _invoke([], tmp_path)
        plan_dirs = list((tmp_path / "plans").iterdir())
        # Should contain company slug and date
        dir_name = plan_dirs[0].name
        assert "my-startup" in dir_name
        assert "2026" in dir_name


# ---------------------------------------------------------------------------
# Contract: --lang flag
# ---------------------------------------------------------------------------


class TestLangFlag:
    def test_lang_en_default(self, tmp_path: Path) -> None:
        _init_company(tmp_path, primary_language="en")
        _invoke([], tmp_path)
        spec = (tmp_path / ".mekong" / "SPEC_OUTPUT.md").read_text(encoding="utf-8")
        assert "Overview" in spec

    def test_lang_vi_output(self, tmp_path: Path) -> None:
        _init_company(tmp_path, primary_language="vi")
        _invoke(["--lang", "vi"], tmp_path)
        spec = (tmp_path / ".mekong" / "SPEC_OUTPUT.md").read_text(encoding="utf-8")
        assert "Tổng quan" in spec

    def test_lang_invalid_exits_nonzero(self, tmp_path: Path) -> None:
        _init_company(tmp_path)
        result = _invoke(["--lang", "fr"], tmp_path)
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Contract: --force overwrites
# ---------------------------------------------------------------------------


class TestForceFlag:
    def test_no_force_on_existing(self, tmp_path: Path) -> None:
        _init_company(tmp_path)
        _invoke([], tmp_path)
        # Second run without force -> error
        result = _invoke([], tmp_path)
        assert result.exit_code == 1

    def test_force_overwrites(self, tmp_path: Path) -> None:
        _init_company(tmp_path)
        _invoke([], tmp_path)
        result = _invoke(["--force"], tmp_path)
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Contract: --dry-run preview
# ---------------------------------------------------------------------------


class TestDryRunFlag:
    def test_dry_run_exits_zero(self, tmp_path: Path) -> None:
        _init_company(tmp_path)
        result = _invoke(["--dry-run"], tmp_path)
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        assert "[DRY RUN]" in result.stdout

    def test_dry_run_no_files_written(self, tmp_path: Path) -> None:
        _init_company(tmp_path)
        result = _invoke(["--dry-run"], tmp_path)
        assert result.exit_code == 0
        assert not (tmp_path / ".mekong" / "SPEC_OUTPUT.md").exists()
        assert not (tmp_path / "plans").exists()


# ---------------------------------------------------------------------------
# Contract: all product types
# ---------------------------------------------------------------------------


class TestProductTypes:
    @pytest.mark.parametrize("product_type", ["saas", "digital", "api_service", "consulting"])
    def test_each_product_type_generates_spec(self, tmp_path: Path, product_type: str) -> None:
        _init_company(tmp_path, product_type=product_type)
        result = _invoke([], tmp_path)
        assert result.exit_code == 0, f"Failed for {product_type}: stdout={result.stdout} stderr={result.stderr}"
        assert (tmp_path / ".mekong" / "SPEC_OUTPUT.md").exists()
        spec_content = (tmp_path / ".mekong" / "SPEC_OUTPUT.md").read_text(encoding="utf-8")
        assert len(spec_content) > 100, f"Spec too short for {product_type}"
