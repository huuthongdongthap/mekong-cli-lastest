# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Visual QA tier tests.

The core invariant: the system NEVER claims visual evidence it does not have.
Playwright is not installed in this environment, so the default provider must
report unavailable and every audit must land on the STATIC tier with an
explicit "no visual evidence" note.
"""

from __future__ import annotations

from pathlib import Path

from src.design_intelligence.visual import (
    LLMVisualJudge,
    PlaywrightProvider,
    VisualEvidence,
    detect_tier,
    run_visual_qa,
)


def test_default_provider_reports_unavailable_without_playwright() -> None:
    """Playwright is absent here — the default provider must say so."""
    assert PlaywrightProvider().available() is False


def test_detect_tier_is_static_when_no_provider() -> None:
    assert detect_tier() == __import__(
        "src.design_intelligence.schemas", fromlist=["VisualQATier"]
    ).VisualQATier.STATIC


def test_visual_judge_reports_unavailable_without_vision() -> None:
    assert LLMVisualJudge().available() is False


class _FakeProvider:
    """In-memory provider for tier tests. Never writes a real PNG."""

    def __init__(self, ok: bool = True, path: Path | None = None) -> None:
        self.ok = ok
        self.path = path

    def available(self) -> bool:
        return True

    def capture(self, target: str, out_path: Path) -> Path:
        if not self.ok:
            raise RuntimeError("render failed")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"FAKE-PNG")
        return out_path


class _FakeJudge:
    def __init__(self, ok: bool = True, scores: dict[str, float] | None = None) -> None:
        self.ok = ok
        self.scores = scores or {}

    def available(self) -> bool:
        return True

    def judge(self, screenshot: Path) -> dict[str, float]:
        if not self.ok:
            raise RuntimeError("judge failed")
        return dict(self.scores)


def test_render_failure_degrades_to_static_with_note(tmp_path: Path) -> None:
    ev = run_visual_qa("http://example.com", tmp_path, screenshot_provider=_FakeProvider(ok=False))
    assert ev.tier.value == "static"
    assert "no visual evidence" in ev.note.lower()
    assert ev.screenshot is None
    assert ev.visual_scores == {}


def test_render_without_judge_is_screenshot_tier(tmp_path: Path) -> None:
    ev = run_visual_qa(
        "http://example.com", tmp_path, screenshot_provider=_FakeProvider()
    )
    assert ev.tier.value == "screenshot"
    assert ev.screenshot is not None
    assert ev.visual_scores == {}
    assert "vision judge unavailable" in ev.note.lower()


def test_render_with_judge_is_full_tier(tmp_path: Path) -> None:
    ev = run_visual_qa(
        "http://example.com",
        tmp_path,
        screenshot_provider=_FakeProvider(),
        visual_judge=_FakeJudge(scores={"v1": 0.8, "v2": 0.6}),
    )
    assert ev.tier.value == "full"
    assert ev.visual_scores == {"v1": 0.8, "v2": 0.6}


def test_judge_failure_degrades_to_screenshot_not_full(tmp_path: Path) -> None:
    ev = run_visual_qa(
        "http://example.com",
        tmp_path,
        screenshot_provider=_FakeProvider(),
        visual_judge=_FakeJudge(ok=False),
    )
    assert ev.tier.value == "screenshot"
    assert ev.visual_scores == {}


def test_visual_evidence_never_overclaims() -> None:
    """A STATIC-tier evidence object must not carry a screenshot or scores."""
    ev = VisualEvidence(
        tier=__import__("src.design_intelligence.schemas", fromlist=["VisualQATier"]).VisualQATier.STATIC,
        note="no visual evidence — screenshot provider unavailable",
    )
    assert ev.screenshot is None
    assert ev.visual_scores == {}
    assert ev.a11y_issues == []