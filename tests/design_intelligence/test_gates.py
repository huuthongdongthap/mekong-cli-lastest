# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Tests for the gate runner. No mocks, no fake data — real HTML fixtures."""

from __future__ import annotations

from pathlib import Path

from src.design_intelligence.gates import (
    evaluate_all,
    run_deterministic_gates,
    run_heuristic_gates,
    run_visual_gates,
    to_findings,
)
from src.design_intelligence.schemas import EvidenceTier

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def _det(gates, gid):
    return next((g for g in gates if g.gate_id == gid), None)


# ---------------------------------------------------------------- slop fixture
class TestSlopFixture:
    def setup_method(self):
        self.html = _load("slop-landing.html")

    def test_default_font_detected(self):
        g = _det(run_deterministic_gates(self.html), "1")
        assert g is not None and g.passed is False

    def test_gradient_text_detected(self):
        g = _det(run_deterministic_gates(self.html), "2")
        assert g is not None and g.passed is False

    def test_three_col_grid_detected(self):
        g = _det(run_deterministic_gates(self.html), "3")
        assert g is not None and g.passed is False

    def test_centred_hero_detected(self):
        g = _det(run_deterministic_gates(self.html), "6")
        assert g is not None and g.passed is False

    def test_pure_black_base_detected(self):
        g = _det(run_deterministic_gates(self.html), "7")
        assert g is not None and g.passed is False

    def test_transition_all_detected(self):
        g = _det(run_deterministic_gates(self.html), "10")
        assert g is not None and g.passed is False

    def test_hover_scale_detected(self):
        g = _det(run_deterministic_gates(self.html), "11")
        assert g is not None and g.passed is False

    def test_bouncy_easing_detected(self):
        g = _det(run_deterministic_gates(self.html), "12")
        assert g is not None and g.passed is False

    def test_layout_motion_detected(self):
        g = _det(run_deterministic_gates(self.html), "14")
        assert g is not None and g.passed is False

    def test_cliche_copy_detected(self):
        g = _det(run_deterministic_gates(self.html), "19")
        assert g is not None and g.passed is False

    def test_macrostructure_stamp_missing(self):
        g = _det(run_deterministic_gates(self.html), "20")
        assert g is not None and g.passed is False

    def test_zero_chroma_neutral_detected(self):
        g = _det(run_deterministic_gates(self.html), "22")
        assert g is not None and g.passed is False

    def test_arbitrary_spacing_detected(self):
        g = _det(run_deterministic_gates(self.html), "24")
        assert g is not None and g.passed is False

    def test_prose_max_width_detected(self):
        g = _det(run_deterministic_gates(self.html), "25")
        assert g is not None and g.passed is False

    def test_focus_state_missing(self):
        g = _det(run_deterministic_gates(self.html), "26")
        assert g is not None and g.passed is False

    def test_motion_without_reduced_fallback(self):
        g = _det(run_deterministic_gates(self.html), "27")
        assert g is not None and g.passed is False

    def test_video_lcp_killer(self):
        g = _det(run_deterministic_gates(self.html), "28")
        assert g is not None and g.passed is False

    def test_emoji_icon_tell(self):
        g = _det(run_deterministic_gates(self.html), "30")
        assert g is not None and g.passed is False

    def test_decorative_svg_no_accessibility(self):
        g = _det(run_deterministic_gates(self.html), "33")
        assert g is not None and g.passed is False

    def test_no_horizontal_scroll_clip(self):
        g = _det(run_deterministic_gates(self.html), "34")
        assert g is not None and g.passed is False

    def test_too_many_font_families(self):
        g = _det(run_deterministic_gates(self.html), "37")
        assert g is not None and g.passed is False

    def test_italic_heading_detected(self):
        g = _det(run_deterministic_gates(self.html), "38a")
        assert g is not None and g.passed is False

    def test_redrawn_chrome_detected(self):
        g = _det(run_deterministic_gates(self.html), "47")
        assert g is not None and g.passed is False

    def test_mid_render_token_improvisation(self):
        g = _det(run_deterministic_gates(self.html), "48")
        assert g is not None and g.passed is False

    def test_image_grid_track_not_minmax(self):
        g = _det(run_deterministic_gates(self.html), "50")
        assert g is not None and g.passed is False

    def test_display_head_no_overflow_wrap(self):
        g = _det(run_deterministic_gates(self.html), "51")
        assert g is not None and g.passed is False

    def test_eyebrow_beside_heading(self):
        g = _det(run_deterministic_gates(self.html), "54")
        assert g is not None and g.passed is False

    def test_all_caps_collision(self):
        g = _det(run_deterministic_gates(self.html), "55")
        assert g is not None and g.passed is False

    def test_sticky_bleed(self):
        g = _det(run_deterministic_gates(self.html), "56")
        assert g is not None and g.passed is False

    def test_at_least_five_objective_failures(self):
        failures = [g for g in run_deterministic_gates(self.html) if not g.passed]
        assert len(failures) >= 5

    def test_objective_evidence_tier(self):
        for g in run_deterministic_gates(self.html):
            assert g.evidence == EvidenceTier.OBJECTIVE


# ---------------------------------------------------------------- good fixture
class TestGoodFixture:
    def setup_method(self):
        self.html = _load("good-dashboard.html")

    def test_no_objective_failures(self):
        failures = [g for g in run_deterministic_gates(self.html) if not g.passed]
        assert failures == []

    def test_macrostructure_stamp_present(self):
        g = _det(run_deterministic_gates(self.html), "20")
        assert g is not None and g.passed is True

    def test_no_horizontal_scroll(self):
        g = _det(run_deterministic_gates(self.html), "34")
        assert g is not None and g.passed is True

    def test_tokens_locked(self):
        g = _det(run_deterministic_gates(self.html), "48")
        assert g is not None and g.passed is True


# ---------------------------------------------------------------- tier separation
class TestTierSeparation:
    def test_heuristic_gates_are_not_objective(self):
        html = _load("slop-landing.html")
        for g in run_heuristic_gates(html):
            assert g.evidence == EvidenceTier.HEURISTIC

    def test_visual_gates_are_opinion(self):
        html = _load("slop-landing.html")
        for g in run_visual_gates(html):
            assert g.evidence == EvidenceTier.OPINION

    def test_evaluate_all_merges_tiers(self):
        html = _load("slop-landing.html")
        results = evaluate_all(html)
        tiers = {r.evidence for r in results}
        assert EvidenceTier.OBJECTIVE in tiers
        assert EvidenceTier.HEURISTIC in tiers
        assert EvidenceTier.OPINION in tiers

    def test_to_findings_skips_passed(self):
        html = _load("slop-landing.html")
        results = evaluate_all(html)
        findings = to_findings(results)
        # Only OBJECTIVE results are "evaluated" — heuristic/visual default to passed
        # but are not yet judged, so they must not appear as findings either.
        evaluated_passed = {
            r.gate_id for r in results
            if r.evidence == EvidenceTier.OBJECTIVE and r.passed
        }
        for f in findings:
            gate_id = f.description.split(":", 1)[0].split("(")[0].strip()
            assert gate_id not in evaluated_passed