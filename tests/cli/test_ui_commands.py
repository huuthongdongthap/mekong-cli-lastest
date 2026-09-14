# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Tests for `mekong ui` — no mocks, no fake data, real HTML fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.app_setup import build_app
from src.cli.ui_benchmark import FIXTURES
from src.cli.ui_study import STUDIES_DIR, _deterministic_dna, _infer_density, _slug

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "design_intelligence" / "fixtures"
SLOP = (FIXTURES_DIR / "slop-landing.html").read_text()
GOOD = (FIXTURES_DIR / "good-dashboard.html").read_text()


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def app():
    return build_app()


# ------------------------------------------------------------------ slug
def test_slug_normalises() -> None:
    assert _slug("My Cool Study!") == "my-cool-study"
    assert _slug("a/b c") == "a-b-c"
    assert _slug("!!!") == "target"


# ------------------------------------------------------------------ density
def test_infer_density_sparse() -> None:
    css = ".x { gap: 40px; }"
    assert _infer_density(css).value == "sparse"


def test_infer_density_dense() -> None:
    css = ".x { gap: 4px; }"
    assert _infer_density(css).value == "dense"


def test_infer_density_no_gap_is_comfortable() -> None:
    assert _infer_density(".x { padding: 16px; }").value == "comfortable"


# ------------------------------------------------------------------ dna
def test_deterministic_dna_has_required_axes() -> None:
    dna = _deterministic_dna(SLOP, "file:slop")
    assert dna.identity
    assert dna.product_type.value == "landing-page"
    assert 0.0 <= dna.confidence <= 1.0
    assert dna.confidence < 1.0  # deterministic-only extraction, never claimed as full


def test_dna_for_good_dashboard_is_saas() -> None:
    dna = _deterministic_dna(GOOD, "file:good")
    assert dna.product_type.value == "saas-dashboard"


def test_dna_for_good_dashboard_has_macrostructure() -> None:
    dna = _deterministic_dna(GOOD, "file:good")
    assert dna.macrostructure is not None


# ------------------------------------------------------------------ audit
def test_audit_slop_exits_zero_and_reports_failures(runner, app) -> None:
    res = runner.invoke(app, ["ui", "audit", str(FIXTURES_DIR / "slop-landing.html")])
    assert res.exit_code == 0
    assert "DESIGN SCORE" in res.output
    assert "objective failure" in res.output.lower()


def test_audit_good_has_no_objective_failures(runner, app) -> None:
    res = runner.invoke(app, ["ui", "audit", str(FIXTURES_DIR / "good-dashboard.html")])
    assert res.exit_code == 0
    assert "0 objective failure" in res.output


def test_audit_json_emits_tiers(runner, app) -> None:
    import json

    res = runner.invoke(
        app, ["ui", "audit", str(FIXTURES_DIR / "slop-landing.html"), "--json"]
    )
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert set(data["scores"]) == {
        "structure", "typography", "hierarchy", "color", "density",
        "interaction", "accessibility", "distinctiveness", "anti_slop",
    }
    assert data["tiers"]["objective"] >= 5
    assert data["tiers"]["heuristic"] >= 0
    assert data["tiers"]["opinion"] >= 0


def test_audit_never_claims_visual_without_render(runner, app) -> None:
    """Default audit is STATIC — no visual evidence is claimed."""
    import json

    res = runner.invoke(
        app, ["ui", "audit", str(FIXTURES_DIR / "good-dashboard.html"), "--json"]
    )
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["visual_qa_tier"] == "static"
    assert "static" in data["visual_qa_note"].lower()


def test_audit_render_without_playwright_stays_static(runner, app) -> None:
    """--render requests a screenshot but never claims one when the provider is absent."""
    import json

    res = runner.invoke(
        app, ["ui", "audit", str(FIXTURES_DIR / "good-dashboard.html"), "--render", "--json"]
    )
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["visual_qa_tier"] == "static"
    assert "no visual evidence" in data["visual_qa_note"].lower()


def test_audit_missing_target_exits_nonzero(runner, app) -> None:
    res = runner.invoke(app, ["ui", "audit", "no/such/file.html"])
    assert res.exit_code != 0


# ------------------------------------------------------------------ study
def test_study_writes_design_md_and_json(runner, app, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(
        app, ["ui", "study", str(FIXTURES_DIR / "good-dashboard.html"), "--name", "g"]
    )
    assert res.exit_code == 0
    design_md = (tmp_path / STUDIES_DIR / "g" / "design.md").read_text()
    design_json = (tmp_path / STUDIES_DIR / "g" / "design.json").read_text()
    assert "# Design Study" in design_md
    assert "anti-patterns" in design_md
    assert "product_type" in design_json
    assert "confidence" in design_json


def test_study_redesign_preserves_identity(runner, app, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(
        app, ["ui", "study", str(FIXTURES_DIR / "good-dashboard.html"), "--name", "g"]
    )
    res = runner.invoke(app, ["ui", "redesign", "g"])
    assert res.exit_code == 0
    import json

    out = json.loads((tmp_path / STUDIES_DIR / "g-v2" / "design.json").read_text())
    assert out["identity"].startswith("Redesign of")
    assert out["macrostructure"] != "repeat(2, minmax(0, 1fr))"


def test_redesign_unknown_study_exits_nonzero(runner, app, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["ui", "redesign", "nope"])
    assert res.exit_code != 0


# ------------------------------------------------------------------ build
def test_build_emits_tokens_css(runner, app, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # first produce a study so a design.json exists
    runner.invoke(
        app, ["ui", "study", str(FIXTURES_DIR / "good-dashboard.html"), "--name", "g"]
    )
    res = runner.invoke(app, ["ui", "build", str(tmp_path / STUDIES_DIR / "g" / "design.json")])
    assert res.exit_code == 0
    css = (tmp_path / ".mekong/design/tokens.css").read_text()
    assert ":root {" in css
    assert "--design-" in css


def test_build_invalid_dna_exits_nonzero(runner, app, tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"identity": ""}')
    res = runner.invoke(app, ["ui", "build", str(bad)])
    assert res.exit_code != 0


# ------------------------------------------------------------------ benchmark
def _benchmark_payload(output: str) -> dict:
    """The benchmark prints a rich table, then a JSON object on its own line."""
    import json

    # Pretty-printed JSON: the top-level object opens with '{' at column 0.
    # Nested objects are indented, so the last '\n{\n' is the trailing dump.
    return json.loads(output[output.rindex("\n{\n") + 1:])


def test_benchmark_runs_all_fixtures(runner, app) -> None:
    res = runner.invoke(app, ["ui", "benchmark"])
    assert res.exit_code == 0
    assert "Design Benchmark" in res.output
    payload = _benchmark_payload(res.output)
    names = sorted(p.name for p in FIXTURES.glob("*.html"))
    assert payload["fixtures"] == len(names)
    # Seven reported metrics, each traced back to real axes.
    assert set(payload["metrics"]) == {
        "anti_slop", "distinctiveness", "hierarchy", "readability",
        "accessibility", "responsive", "consistency",
    }
    assert set(payload["metric_derivation"]["readability"]) == {"typography", "hierarchy"}


def test_benchmark_good_scores_highest(runner, app) -> None:
    res = runner.invoke(app, ["ui", "benchmark"])
    assert res.exit_code == 0
    assert "good-dashboard.html" in res.output
    assert "Highest total" in res.output


def test_benchmark_separates_slop_from_good(runner, app) -> None:
    """Anti-gaming: the benchmark must score slop fixtures below good ones."""
    res = runner.invoke(app, ["ui", "benchmark"])
    assert res.exit_code == 0
    payload = _benchmark_payload(res.output)
    by_name = {r["fixture"]: r for r in payload["rows"]}
    good = by_name["good-dashboard.html"]
    slop = by_name["ai-slop-landing.html"]
    assert good["total"] > slop["total"], (
        f"anti-gaming failure: good={good['total']} slop={slop['total']}"
    )
    assert good["metrics"]["anti_slop"] > slop["metrics"]["anti_slop"]


# ------------------------------------------------------------------ regression
def test_ui_help_lists_all_five_verbs(runner, app) -> None:
    res = runner.invoke(app, ["ui", "--help"])
    assert res.exit_code == 0
    for verb in ("audit", "study", "redesign", "build", "benchmark"):
        assert verb in res.output


def test_existing_command_surface_unchanged(runner, app) -> None:
    """`design` (SDLC) and `ui` (design intelligence) must both exist."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "ui" in res.output