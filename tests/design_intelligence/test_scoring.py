# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Tests for the scoring engine. No mocks — real fixtures, real gate results."""

from __future__ import annotations

from pathlib import Path

from src.design_intelligence.gates import evaluate_all
from src.design_intelligence.schemas import VisualQATier
from src.design_intelligence.scoring import (
    build_audit_report,
    recommend_fixes,
    score_axes,
    score_and_report,
)
from src.design_intelligence.schemas import AuditReport

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


class TestAxisScores:
    def test_all_nine_axes_present(self):
        scores = score_axes(evaluate_all(_load("slop-landing.html")))
        assert set(scores.model_dump()) == {
            "structure", "typography", "hierarchy", "color", "density",
            "interaction", "accessibility", "distinctiveness", "anti_slop",
        }

    def test_scores_in_range(self):
        scores = score_axes(evaluate_all(_load("slop-landing.html")))
        for value in scores.model_dump().values():
            assert 0 <= value <= 100

    def test_slop_fixture_docks_axes(self):
        scores = score_axes(evaluate_all(_load("slop-landing.html")))
        assert scores.typography < 100
        assert scores.structure < 100

    def test_clean_fixture_keeps_axes_high(self):
        scores = score_axes(evaluate_all(_load("good-dashboard.html")))
        assert scores.structure >= 80
        assert scores.accessibility >= 80


class TestCriticalFailures:
    def test_slop_fixture_has_criticals(self):
        results = evaluate_all(_load("slop-landing.html"))
        report = build_audit_report("slop", results)
        assert len(report.critical_failures) >= 1

    def test_clean_fixture_has_no_criticals(self):
        results = evaluate_all(_load("good-dashboard.html"))
        report = build_audit_report("good", results)
        assert report.critical_failures == []


class TestReportShape:
    def test_report_is_typed(self):
        results = evaluate_all(_load("slop-landing.html"))
        report = build_audit_report("slop", results, VisualQATier.STATIC)
        assert isinstance(report, AuditReport)
        assert report.target == "slop"
        assert report.visual_qa_tier == VisualQATier.STATIC
        assert report.scores is not None

    def test_recommended_fixes_non_empty_for_slop(self):
        results = evaluate_all(_load("slop-landing.html"))
        assert recommend_fixes(results)

    def test_recommended_fixes_empty_for_clean(self):
        results = evaluate_all(_load("good-dashboard.html"))
        assert recommend_fixes(results) == []


class TestScoreAndReport:
    def test_convenience_returns_both(self):
        report = score_and_report("slop", evaluate_all(_load("slop-landing.html")))
        assert report.scores is not None
        assert report.findings is not None
        assert report.critical_failures is not None
        assert report.recommended_fixes is not None