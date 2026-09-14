# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""`mekong ui benchmark` — 10 representative fixtures, axis deltas.

Not a single static target. Each fixture is a known archetype; the benchmark
reports how the deterministic gates score it, so the suite cannot be gamed by
tuning one example. The scorer reads the fixtures from disk and applies the
gate rules — the fixtures are never in the scorer's path.

Nine scoring axes are the source of truth; the seven reported metrics below
are derived from them (see _METRICS). Every metric names the axes it folds
together so the derivation is auditable, not a second opinion.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.design_intelligence.gates import run_deterministic_gates
from src.design_intelligence.scoring import AxisScores, score_axes

console = Console()

FIXTURES = Path(__file__).resolve().parent.parent.parent / "tests" / "design_intelligence" / "fixtures"

# Seven reported metrics, each folded from the nine real scoring axes.
# The mapping is explicit so a reader can trace any metric back to gates.
_METRICS: dict[str, tuple[str, ...]] = {
    "anti_slop": ("anti_slop",),
    "distinctiveness": ("distinctiveness",),
    "hierarchy": ("hierarchy",),
    "readability": ("typography", "hierarchy"),
    "accessibility": ("accessibility",),
    "responsive": ("structure",),
    "consistency": ("color", "distinctiveness"),
}

_AXES = (
    "structure", "typography", "hierarchy", "color", "density",
    "interaction", "accessibility", "distinctiveness", "anti_slop",
)


def _fixture(name: str) -> tuple[str, str]:
    p = FIXTURES / name
    return p.read_text(encoding="utf-8"), p.name


def _metrics(scores: AxisScores) -> dict[str, int]:
    """Fold the nine axis scores into the seven reported metrics."""
    out: dict[str, int] = {}
    for metric, axes in _METRICS.items():
        out[metric] = round(sum(getattr(scores, a) for a in axes) / len(axes))
    return out


def run_benchmark() -> None:
    names = sorted(p.name for p in FIXTURES.glob("*.html"))
    if not names:
        console.print("[red]✗[/red] No benchmark fixtures found")
        return

    rows: list[dict[str, object]] = []
    table = Table(title="Design Benchmark — axis scores")
    table.add_column("fixture", style="bold")
    for axis in _AXES:
        table.add_column(axis.replace("_", " ").title(), justify="right")

    worst: list[tuple[str, int]] = []
    for name in names:
        html, label = _fixture(name)
        scores = score_axes(run_deterministic_gates(html))
        total = sum(getattr(scores, a) for a in _AXES)
        worst.append((label, total))
        table.add_row(label, *[str(getattr(scores, a)) for a in _AXES])
        rows.append({"fixture": label, "axes": scores.model_dump(), "metrics": _metrics(scores), "total": total})

    console.print(table)
    worst.sort(key=lambda x: x[1])
    console.print(f"\n[dim]Lowest total: {worst[0][0]} ({worst[0][1]})[/dim]")
    console.print(f"[dim]Highest total: {worst[-1][0]} ({worst[-1][1]})[/dim]")
    console.print(json.dumps({
        "fixtures": len(names),
        "metrics": list(_METRICS),
        "metric_derivation": {m: list(a) for m, a in _METRICS.items()},
        "worst": worst[0],
        "best": worst[-1],
        "rows": rows,
    }, indent=2))