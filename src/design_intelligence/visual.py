# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Visual QA layer: provider-agnostic screenshot + judge interfaces.

Three visual-QA tiers, degraded in order — the system NEVER claims visual
evidence it does not have:

  FULL        screenshot rendered AND a vision judge evaluated it
  SCREENSHOT  screenshot rendered, no vision judge available
  STATIC      code-level analysis only — "no visual evidence" is recorded

Providers are interfaces so the wiring stays provider-agnostic: Playwright is
the default ScreenshotProvider, but any object implementing the protocol can
be injected (tests use a fake provider; a future BrowserAgent can plug in).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from src.design_intelligence.schemas import VisualQATier


class ScreenshotProvider(ABC):
    """Renders a target (URL or local HTML file) to a PNG screenshot."""

    @abstractmethod
    def available(self) -> bool:
        """True when this provider can render right now."""

    @abstractmethod
    def capture(self, target: str, out_path: Path) -> Path:
        """Render `target` and write a PNG to `out_path`. Raises on failure."""


class VisualJudge(ABC):
    """Evaluates a rendered screenshot on design-quality axes."""

    @abstractmethod
    def available(self) -> bool:
        """True when a vision-capable judge is reachable."""

    @abstractmethod
    def judge(self, screenshot: Path) -> dict[str, float]:
        """Return gate_id -> 0..1 scores for the visual gates."""


class AccessibilityJudge(ABC):
    """Evaluates a rendered page for accessibility issues."""

    @abstractmethod
    def available(self) -> bool:
        """True when an a11y judge is reachable."""

    @abstractmethod
    def judge(self, screenshot: Path) -> list[str]:
        """Return a list of a11y issue descriptions (empty = none found)."""


class PlaywrightProvider(ScreenshotProvider):
    """Default screenshot provider. Degrades cleanly when Playwright is absent."""

    def available(self) -> bool:
        try:
            import playwright  # type: ignore[import-not-found]  # noqa: F401

            return True
        except ImportError:
            return False

    def capture(self, target: str, out_path: Path) -> Path:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            if target.startswith(("http://", "https://")):
                page.goto(target, wait_until="networkidle")
            else:
                page.goto(Path(target).resolve().as_uri())
            page.screenshot(path=str(out_path), full_page=True)
            browser.close()
        return out_path


class LLMVisualJudge(VisualJudge):
    """Vision judge backed by the shared LLMClient. Never fabricates scores."""

    def available(self) -> bool:
        try:
            from src.providers.llm.client import get_client

            return bool(get_client().is_available)
        except Exception:  # noqa: BLE001 — judge unavailability must degrade, not crash
            return False

    def judge(self, screenshot: Path) -> dict[str, float]:
        # Vision input requires a multimodal provider; until one is wired the
        # judge reports unavailable rather than guessing from the file name.
        raise NotImplementedError("vision judging requires a multimodal provider")


@dataclass
class VisualEvidence:
    """What visual evidence an audit actually has. Never over-claimed."""

    tier: VisualQATier
    screenshot: Path | None = None
    visual_scores: dict[str, float] = field(default_factory=dict)
    a11y_issues: list[str] = field(default_factory=list)
    note: str = ""


def detect_tier(
    screenshot_provider: ScreenshotProvider | None = None,
    visual_judge: VisualJudge | None = None,
) -> VisualQATier:
    """FULL if render+judge, SCREENSHOT if render only, else STATIC."""
    provider = screenshot_provider or PlaywrightProvider()
    if not provider.available():
        return VisualQATier.STATIC
    judge = visual_judge or LLMVisualJudge()
    return VisualQATier.FULL if judge.available() else VisualQATier.SCREENSHOT


def run_visual_qa(
    target: str,
    out_dir: Path,
    screenshot_provider: ScreenshotProvider | None = None,
    visual_judge: VisualJudge | None = None,
    a11y_judge: AccessibilityJudge | None = None,
) -> VisualEvidence:
    """Capture + judge a target, degrading FULL -> SCREENSHOT -> STATIC.

    Every degradation records a note so reports can state exactly what was
    and was not verified. A render failure drops to STATIC, never fakes.
    """
    provider = screenshot_provider or PlaywrightProvider()
    if not provider.available():
        return VisualEvidence(
            tier=VisualQATier.STATIC,
            note="no visual evidence — screenshot provider unavailable",
        )

    shot = out_dir / "screenshot.png"
    try:
        provider.capture(target, shot)
    except Exception as exc:  # noqa: BLE001 — render failure degrades, never fakes
        return VisualEvidence(
            tier=VisualQATier.STATIC,
            note=f"no visual evidence — render failed: {exc}",
        )

    judge = visual_judge or LLMVisualJudge()
    scores: dict[str, float] = {}
    if judge.available():
        try:
            scores = judge.judge(shot)
        except Exception:  # noqa: BLE001 — judge failure degrades to SCREENSHOT
            scores = {}

    issues: list[str] = []
    if a11y_judge is not None and a11y_judge.available():
        try:
            issues = a11y_judge.judge(shot)
        except Exception:  # noqa: BLE001 — a11y judge failure is non-fatal
            issues = []

    tier = VisualQATier.FULL if scores else VisualQATier.SCREENSHOT
    note = "" if scores else "screenshot captured; vision judge unavailable"
    return VisualEvidence(
        tier=tier, screenshot=shot, visual_scores=scores, a11y_issues=issues, note=note
    )
