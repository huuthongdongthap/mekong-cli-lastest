# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""`mekong ui` — native design-intelligence commands (Hallmark verbs, MIT).

Sub-app with five verbs, each a thin orchestrator over src/design_intelligence:

  build     emit a tokenized design system from a DesignDNA file
  audit     deterministic gate run + 9-axis DESIGN SCORE block
  study     fetch/inspect a target -> DesignDNA + .mekong/design/studies/<name>/design.md
  redesign  re-fingerprint an existing study (preserve copy/IA/brand)
  benchmark run the benchmark fixtures and report axis deltas

Three evidence tiers are kept strictly separate in every audit:
  OBJECTIVE — deterministic regex/static check (always runs)
  HEURISTIC — LLM judge (only with --llm; otherwise marked UNVERIFIED)
  OPINION    — requires a rendered screenshot (never claimed without one)

No command fabricates results. When the LLM judge is unavailable every heuristic
finding is marked UNVERIFIED with confidence 0.0 — never a fake pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from src.design_intelligence.gates import evaluate_all
from src.design_intelligence.schemas import DesignDNA
from src.design_intelligence.scoring import score_and_report
from src.design_intelligence.visual import detect_tier, run_visual_qa

console = Console()

ui_app = typer.Typer(
    name="ui",
    help="Design intelligence: audit, study, redesign, build, benchmark",
    no_args_is_help=True,
)

DESIGN_DIR = Path(".mekong/design")
STUDIES_DIR = DESIGN_DIR / "studies"

_AXES = (
    "structure", "typography", "hierarchy", "color", "density",
    "interaction", "accessibility", "distinctiveness", "anti_slop",
)


# ------------------------------------------------------------------ helpers
def _read_target(target: str) -> tuple[str, str]:
    """Return (html, source_label) for a path or URL. Raises typer.Exit on failure."""
    p = Path(target)
    if p.exists():
        return p.read_text(encoding="utf-8"), f"file:{p}"
    import httpx

    try:
        resp = httpx.get(target, follow_redirects=True, timeout=30.0)
        resp.raise_for_status()
    except Exception as exc:
        console.print(f"[red]✗[/red] Could not fetch {target}: {exc}")
        raise typer.Exit(1) from exc
    return resp.text, f"url:{target}"


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "target"


def _print_score_block(report: Any) -> None:
    """Render the DESIGN SCORE block from a score_and_report result."""
    scores = report.scores
    table = Table(title="DESIGN SCORE", show_header=False, header_style="bold")
    table.add_column("axis", style="bold")
    table.add_column("score", justify="right")
    for axis in _AXES:
        table.add_row(axis.replace("_", " ").title(), str(getattr(scores, axis)))
    console.print(table)
    if report.critical_failures:
        console.print("[red]Critical failures:[/red]")
        for line in report.critical_failures:
            console.print(f"  [red]•[/red] {line}")
    if report.recommended_fixes:
        console.print("[yellow]Recommended fixes:[/yellow]")
        for line in report.recommended_fixes:
            console.print(f"  [yellow]→[/yellow] {line}")


# ------------------------------------------------------------------ audit
@ui_app.command(name="audit")
def audit_cmd(
    target: str = typer.Argument(..., help="HTML file path or URL to audit"),
    llm: bool = typer.Option(False, "--llm", help="Run the LLM judge on heuristic gates"),
    render: bool = typer.Option(False, "--render", help="Capture a screenshot for visual gates"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of the score block"),
) -> None:
    """Deterministic gate run + 9-axis score. Never claims visual evidence."""
    html, source = _read_target(target)
    heuristic_scores = _llm_judge_scores(html) if llm else None

    visual = run_visual_qa(target, DESIGN_DIR / "visual") if render else None
    visual_scores = visual.visual_scores if visual else None
    results = evaluate_all(html, heuristic_scores=heuristic_scores, visual_scores=visual_scores)
    report = score_and_report(source, results)
    tier = visual.tier if visual else detect_tier()
    tier_note = visual.note if visual else "static analysis only — rerun with --render"

    objective = [r for r in results if r.evidence == "objective"]
    heuristic = [r for r in results if r.evidence == "heuristic"]
    opinion = [r for r in results if r.evidence == "opinion"]

    if json_out:
        console.print_json(json.dumps({
            "target": source,
            "scores": report.scores.model_dump(),
            "critical_failures": report.critical_failures,
            "recommended_fixes": report.recommended_fixes,
            "findings": [f.model_dump() for f in report.findings],
            "visual_qa_tier": tier.value,
            "visual_qa_note": tier_note,
            "tiers": {
                "objective": len(objective),
                "heuristic": len(heuristic),
                "opinion": len(opinion),
            },
        }))
        return
    _print_score_block(report)
    n_fail = sum(1 for r in objective if not r.passed)
    console.print(
        f"\n[dim]{n_fail} objective failure(s) across {len(objective)} automatic gates; "
        f"{len(heuristic)} heuristic (LLM judge {'ran' if llm else 'skipped'}); "
        f"{len(opinion)} visual gates.[/dim]"
    )
    console.print(f"[dim]visual QA tier: {tier.value} — {tier_note}[/dim]")


def _llm_judge_scores(html: str) -> dict[str, float] | None:
    """Ask the LLM judge for heuristic gate scores. Returns None if no provider."""
    try:
        from src.providers.llm.client import get_client

        client = get_client()
        prompt = (
            "You are a design judge. Score this HTML on a 0-1 scale for each of these "
            "gate ids (return ONLY a JSON object mapping id -> float):\n"
            + ", ".join(str(i) for i in range(1, 59))
            + "\nHTML:\n" + html[:4000]
        )
        data = client.generate_json(prompt)
        return {str(k): float(v) for k, v in data.items() if 0.0 <= float(v) <= 1.0}
    except Exception as exc:  # noqa: BLE001 — LLM unavailable must not break audit
        console.print(f"[yellow]⚠[/yellow] LLM judge unavailable ({exc}); heuristic tier UNVERIFIED")
        return None


# ------------------------------------------------------------------ build
@ui_app.command(name="build")
def build_cmd(
    dna: str = typer.Argument(..., help="DesignDNA JSON file"),
) -> None:
    """Emit a tokenized design system (CSS variables) from a DesignDNA file."""
    data = json.loads(Path(dna).read_text(encoding="utf-8"))
    design = DesignDNA.model_validate(data)
    lines = [
        "/* Mekong Design · auto-generated tokens */",
        f"/* macrostructure: {design.macrostructure or 'unspecified'} */",
        ":root {",
    ]
    for axis, value in design.model_dump().items():
        if isinstance(value, str) and value:
            token = "--design-" + axis.replace("_", "-")
            lines.append(f"  {token}: {value};")
    lines.append("}")
    out_path = DESIGN_DIR / "tokens.css"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[green]✓[/green] Wrote {out_path} ({len(lines)} lines)")


# ------------------------------------------------------------------ study
@ui_app.command(name="study")
def study_cmd(
    target: str = typer.Argument(..., help="URL or local image/HTML to study"),
    name: str = typer.Option("target", "--name", help="Study name (folder)"),
    llm: bool = typer.Option(False, "--llm", help="Run the LLM judge on heuristic gates"),
    export_json: bool = typer.Option(
        False, "--export-json", help="Also emit the DesignDNA JSON to stdout (Sophia contract)"
    ),
) -> None:
    """Analyse a target -> DesignDNA + .mekong/design/studies/<name>/design.md."""
    from src.cli.ui_study import run_study

    run_study(target, name, llm=llm, export_json=export_json)


# ------------------------------------------------------------------ redesign
@ui_app.command(name="redesign")
def redesign_cmd(
    study: str = typer.Argument(..., help="Existing study folder under .mekong/design/studies/"),
    out: str = typer.Option(None, "--out", help="Output study folder (default: <study>-v2)"),
) -> None:
    """Re-fingerprint a study: preserve copy/IA/brand, change macrostructure."""
    from src.cli.ui_study import run_redesign

    run_redesign(study, out)


# ------------------------------------------------------------------ approve
@ui_app.command(name="approve")
def approve_cmd(
    study: str = typer.Argument(..., help="Study folder under .mekong/design/studies/"),
    reject: bool = typer.Option(
        False, "--reject", help="Record the study as a rejected pattern instead"
    ),
    reason: str = typer.Option("", "--reason", help="Reason recorded with the decision"),
) -> None:
    """Approve (or --reject) a study into design memory for agent reuse.

    Only approved DNA enters the `design:` memory namespace — unapproved
    studies stay on disk but are never offered to downstream agents.
    """
    from src.design_intelligence.design_memory import approve_design, reject_pattern

    src_json = STUDIES_DIR / _slug(study) / "design.json"
    if not src_json.exists():
        console.print(f"[red]✗[/red] No study at {src_json}. Run `mekong ui study` first.")
        raise typer.Exit(1)

    if reject:
        reject_pattern(_slug(study), reason or "rejected by operator")
        console.print(f"[yellow]✗[/yellow] Rejected pattern recorded: {_slug(study)}")
        return

    dna = DesignDNA.model_validate(json.loads(src_json.read_text(encoding="utf-8")))
    approve_design(_slug(study), dna, audit_summary=reason or "approved by operator")
    console.print(f"[green]✓[/green] Approved design stored in memory: {_slug(study)}")
    console.print("[dim]  Reuse via `mekong ui build` or the design: memory namespace.[/dim]")


# ------------------------------------------------------------------ benchmark
@ui_app.command(name="benchmark")
def benchmark_cmd() -> None:
    """Run the benchmark fixtures and report axis deltas (no single static target)."""
    from src.cli.ui_benchmark import run_benchmark

    run_benchmark()


def register_ui_commands(app: typer.Typer) -> None:
    """Wire the ui sub-app into the root Typer app."""
    app.add_typer(
        ui_app,
        name="ui",
        help="Design intelligence: audit, study, redesign, build, benchmark",
    )