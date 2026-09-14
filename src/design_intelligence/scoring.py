# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Scoring engine for the Design Intelligence audit.

Nine axes, each 0-100, seeded at 100 and docked by severity. Critical findings
block the axis outright; high/medium/low dock points. Findings below low severity
are recorded but never dock. Adapted from Hallmark's slop test
(github.com/nutlope/hallmark, MIT).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.design_intelligence.gates import GateResult, to_findings
from src.design_intelligence.schemas import (
    AxisScores,
    AuditFinding,
    AuditReport,
    VisualQATier,
)

_SEVERITY_POINTS = {"critical": 30, "high": 20, "medium": 10, "low": 5}
_SEVERITY_BLOCK = {"critical", "high"}

_AXIS_FOR_CATEGORY = {
    "TYPOGRAPHY": "typography",
    "COLOR": "color",
    "STRUCTURE": "structure",
    "COMPONENTS": "interaction",
    "INTERACTION": "interaction",
    "MOTION": "interaction",
    "CONTENT": "hierarchy",
    "SPACING": "density",
    "ACCESSIBILITY": "accessibility",
    "RESPONSIVENESS": "structure",
    "DISTINCTIVENESS": "distinctiveness",
    "AI-SLOP": "anti_slop",
}

_AXES = (
    "structure", "typography", "hierarchy", "color", "density",
    "interaction", "accessibility", "distinctiveness", "anti_slop",
)


@dataclass
class ScoreReport:
    scores: AxisScores
    critical_failures: list[str]
    recommended_fixes: list[str]
    findings: list[AuditFinding]


def _axis_score(axis: str, findings: list[AuditFinding]) -> int:
    score = 100
    for f in findings:
        if _AXIS_FOR_CATEGORY.get(_category_of(f)) != axis:
            continue
        if f.severity in _SEVERITY_BLOCK:
            return 0
        score -= _SEVERITY_POINTS.get(f.severity, 5)
    return max(0, score)


def _category_of(finding: AuditFinding) -> str:
    head = finding.description.split(":", 1)[0]
    m = re.search(r"\(([^)]+)\)", head)
    return m.group(1) if m else head


def score_axes(results: list[GateResult]) -> AxisScores:
    """Compute the nine axis scores from gate results."""
    findings = to_findings(results)
    scores = {axis: _axis_score(axis, findings) for axis in _AXES}
    return AxisScores(**scores)


def identify_critical_failures(results: list[GateResult]) -> list[str]:
    """Return one-line descriptions of every critical/high finding."""
    failures: list[str] = []
    for r in results:
        if r.passed:
            continue
        if r.severity in _SEVERITY_BLOCK:
            failures.append(f"[{r.gate_id}] {r.category}: {r.description}")
    return failures


def recommend_fixes(results: list[GateResult]) -> list[str]:
    """One actionable fix per failed gate, ordered by severity."""
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    failed = sorted(
        (r for r in results if not r.passed),
        key=lambda r: order.get(r.severity, 4),
    )
    return [
        f"[{r.gate_id}] {r.description} -> {r.failure_example or 'review the gate'}"
        for r in failed
    ]


def build_audit_report(
    target: str,
    results: list[GateResult],
    visual_tier: VisualQATier = VisualQATier.STATIC,
) -> AuditReport:
    """Assemble the typed AuditReport from gate results."""
    findings = to_findings(results)
    return AuditReport(
        target=target,
        visual_qa_tier=visual_tier,
        scores=score_axes(results),
        critical_failures=identify_critical_failures(results),
        recommended_fixes=recommend_fixes(results),
        findings=findings,
    )


def score_and_report(
    target: str,
    results: list[GateResult],
    visual_tier: VisualQATier = VisualQATier.STATIC,
) -> ScoreReport:
    """Convenience: score + report in one call."""
    return ScoreReport(
        scores=score_axes(results),
        critical_failures=identify_critical_failures(results),
        recommended_fixes=recommend_fixes(results),
        findings=to_findings(results),
    )