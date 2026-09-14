# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Gate runner for the Design Intelligence layer.

Three evidence tiers, kept strictly separate:
  OBJECTIVE  — deterministic regex/static check on HTML+CSS text (checks.py)
  HEURISTIC — pattern inference / LLM judge, carries a confidence value
  OPINION    — requires a rendered screenshot; never claimed without one

Adapted from Hallmark's slop test (github.com/nutlope/hallmark, MIT).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from src.design_intelligence.checks import CHECKS
from src.design_intelligence.schemas import AuditFinding, EvidenceTier

_KNOWN = Path(__file__).resolve().parent / "knowledge" / "gates.yaml"


@dataclass
class GateResult:
    gate_id: str
    category: str
    severity: str
    description: str
    passed: bool
    evidence: str
    confidence: float | None
    location: str | None = None
    failure_example: str | None = None


def _load_gates(path: Path = _KNOWN) -> list[dict[str, Any]]:
    with Path(path).open() as fh:
        return list(yaml.safe_load(fh)["gates"])


def _extract_css(html: str) -> str:
    """Pull <style>...</style> contents out of the HTML, fall back to empty."""
    m = re.search(r"<style[^>]*>(.*?)</style>", html, re.S | re.I)
    return m.group(1) if m else ""


def run_deterministic_gates(html: str, css: str | None = None) -> list[GateResult]:
    """Run every automatic check. Returns one GateResult per gate (passed or failed)."""
    css = css if css is not None else _extract_css(html)
    results: list[GateResult] = []
    for gate in _load_gates():
        gid = str(gate["id"])
        check = CHECKS.get(gid)
        if check is None or not gate.get("automatic"):
            continue
        failed = check(html, css)
        results.append(
            GateResult(
                gate_id=gid,
                category=gate["category"],
                severity=gate["severity"],
                description=gate["description"],
                passed=not failed,
                evidence=EvidenceTier.OBJECTIVE,
                confidence=1.0 if failed else 0.0,
                location=gate.get("failure_example"),
                failure_example=gate.get("failure_example"),
            )
        )
    return results


def run_heuristic_gates(html: str, css: str | None = None) -> list[GateResult]:
    """Flag gates that need an LLM judge. No LLM call here — the caller supplies it.

    Returns GateResult entries with evidence=HEURISTIC and confidence=None until the
    caller fills them in via fill_heuristic_confidence(). Gates are marked passed=True
    by default — they are "not yet evaluated", not "failed".
    """
    css = css if css is not None else _extract_css(html)
    results: list[GateResult] = []
    for gate in _load_gates():
        if gate.get("automatic"):
            continue
        results.append(
            GateResult(
                gate_id=str(gate["id"]),
                category=gate["category"],
                severity=gate["severity"],
                description=gate["description"],
                passed=True,
                evidence=EvidenceTier.HEURISTIC,
                confidence=None,
                failure_example=gate.get("failure_example"),
            )
        )
    return results


def run_visual_gates(html: str, css: str | None = None) -> list[GateResult]:
    """Gates that only make sense against a rendered screenshot.

    Marked passed=True by default — they are "not yet evaluated", not "failed".
    """
    css = css if css is not None else _extract_css(html)
    results: list[GateResult] = []
    for gate in _load_gates():
        if not gate.get("visual"):
            continue
        results.append(
            GateResult(
                gate_id=str(gate["id"]),
                category=gate["category"],
                severity=gate["severity"],
                description=gate["description"],
                passed=True,
                evidence=EvidenceTier.OPINION,
                confidence=None,
                failure_example=gate.get("failure_example"),
            )
        )
    return results


def fill_heuristic_confidence(results: list[GateResult], scores: dict[str, float]) -> None:
    """Attach a confidence value to every heuristic result. scores: gate_id -> 0..1."""
    for r in results:
        if r.evidence == EvidenceTier.HEURISTIC:
            r.confidence = scores.get(r.gate_id, 0.5)


def evaluate_all(
    html: str,
    css: str | None = None,
    heuristic_scores: dict[str, float] | None = None,
    visual_scores: dict[str, float] | None = None,
) -> list[GateResult]:
    """Run all three tiers and merge. heuristic/visual scores are gate_id -> 0..1."""
    results = run_deterministic_gates(html, css)
    heuristic = run_heuristic_gates(html, css)
    visual = run_visual_gates(html, css)
    if heuristic_scores:
        fill_heuristic_confidence(heuristic, heuristic_scores)
    if visual_scores:
        fill_heuristic_confidence(visual, visual_scores)
    return results + heuristic + visual


def to_findings(results: list[GateResult]) -> list[AuditFinding]:
    """Map gate results onto the typed AuditFinding schema.

    Heuristic findings must expose a confidence value. When the caller has not
    supplied one, a conservative 0.5 is recorded so the finding is never silently
    dropped — the caller can tighten it once the LLM judge runs.
    """
    findings: list[AuditFinding] = []
    for r in results:
        if r.passed:
            continue
        confidence = r.confidence
        if r.evidence == EvidenceTier.HEURISTIC and confidence is None:
            confidence = 0.5
        findings.append(
            AuditFinding(
                description=f"{r.gate_id} ({r.category}): {r.description}",
                location=r.failure_example,
                evidence=EvidenceTier(r.evidence),
                confidence=confidence,
                severity=r.severity,
            )
        )
    return findings