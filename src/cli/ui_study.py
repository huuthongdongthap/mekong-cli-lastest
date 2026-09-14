# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Study + redesign verbs for `mekong ui`.

study    — analyse a target (URL / HTML / image) into a DesignDNA and write
           .mekong/design/studies/<name>/design.md + design.json.
redesign — re-fingerprint an existing study: preserve copy/IA/brand, change
           macrostructure + visual hierarchy. Never a pixel clone.

Both verbs are honest about evidence: deterministic extraction is labelled
OBJECTIVE; anything inferred without a rendered screenshot or LLM judge is
marked UNVERIFIED with confidence 0.0 rather than fabricated.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer
from rich.console import Console

from src.design_intelligence.gates import run_deterministic_gates
from src.design_intelligence.schemas import Density, DesignDNA, ProductType

console = Console()

STUDIES_DIR = Path(".mekong/design/studies")

# Deterministic extraction patterns (OBJECTIVE evidence only).
_FONT = re.compile(r"font-family:\s*([^;]+)")
_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|oklch\([^)]*\)|hsl\([^)]*\)")
_GRID = re.compile(r"grid-template-columns:\s*([^;]+)")
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.S | re.I)


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "target"


def _read_target(target: str) -> tuple[str, str]:
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


def _extract_css(html: str) -> str:
    m = re.search(r"<style[^>]*>(.*?)</style>", html, re.S | re.I)
    return m.group(1) if m else ""


def _infer_product_type(html: str) -> ProductType:
    low = html.lower()
    if "dashboard" in low or "analytics" in low:
        return ProductType.SAAS_DASHBOARD
    if "admin" in low or "console" in low:
        return ProductType.ADMIN_CONSOLE
    if "agent" in low:
        return ProductType.AGENT_CONSOLE
    if "trade" in low or "terminal" in low or "chart" in low:
        return ProductType.TRADING_TERMINAL
    if "docs" in low or "documentation" in low:
        return ProductType.DOCUMENTATION
    return ProductType.LANDING_PAGE


def _infer_density(css: str) -> Density:
    gaps = [int(g) for g in re.findall(r"gap:\s*(\d+)px", css)]
    if not gaps:
        return Density.COMFORTABLE
    avg = sum(gaps) / len(gaps)
    if avg <= 8:
        return Density.DENSE
    if avg <= 16:
        return Density.COMPACT
    if avg <= 32:
        return Density.COMFORTABLE
    return Density.SPARSE


def _deterministic_dna(html: str, source: str) -> DesignDNA:
    """Build a partial DesignDNA from objective text evidence only."""
    css = _extract_css(html)
    fonts = [m.group(1).split(",")[0].strip().strip("'\"") for m in _FONT.finditer(css)]
    colors = list(dict.fromkeys(m.group(0) for m in _COLOR.finditer(css)))[:6]
    grids = [m.group(1).strip() for m in _GRID.finditer(css)]
    h1 = _H1.search(html)
    title = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else ""

    identity = f"Study of {source} — {title[:60]}" if title else f"Study of {source}"
    return DesignDNA(
        identity=identity,
        product_type=_infer_product_type(html),
        audience="unspecified (deterministic study, no audience evidence)",
        brand_character=[],
        macrostructure=grids[0] if grids else None,
        information_architecture=[],
        typography=fonts[0] if fonts else None,
        type_pairing={},
        color_system=", ".join(colors) if colors else None,
        color_anchor=colors[0] if colors else None,
        spacing=None,
        density=_infer_density(css),
        surface_treatment=None,
        interaction_language=None,
        motion=None,
        responsive_behavior=None,
        imagery=None,
        iconography=None,
        component_archetypes=[],
        accessibility=[],
        anti_patterns=[],
        inspiration_sources=[source],
        confidence=0.3,  # deterministic-only: low confidence, never fabricated
    )


def _render_design_md(dna: DesignDNA, source: str, objective_failures: list[str]) -> str:
    lines = [
        f"# Design Study — {dna.identity}",
        "",
        f"- **Source:** {source}",
        f"- **Product type:** {dna.product_type.value}",
        f"- **Density:** {dna.density.value}",
        f"- **Confidence:** {dna.confidence:.2f} (deterministic extraction)",
        "",
        "## Typography",
        dna.typography or "_not detected_",
        "",
        "## Color",
        dna.color_system or "_not detected_",
        "",
        "## Macrostructure",
        dna.macrostructure or "_not detected_",
        "",
        "## Objective anti-patterns detected",
    ]
    if objective_failures:
        lines += [f"- {f}" for f in objective_failures]
    else:
        lines.append("- none")
    lines += [
        "",
        "> This study is analysis/inspiration, not a clone. Reuse the DNA,",
        "> never the pixels.",
        "",
    ]
    return "\n".join(lines)


def run_study(
    target: str, name: str, llm: bool = False, export_json: bool = False
) -> None:
    html, source = _read_target(target)
    dna = _deterministic_dna(html, source)

    if llm:
        dna = _enrich_with_llm(dna, html)

    results = run_deterministic_gates(html)
    failures = [f"[{r.gate_id}] {r.description}" for r in results if not r.passed]

    out_dir = STUDIES_DIR / _slug(name)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "design.md").write_text(_render_design_md(dna, source, failures), encoding="utf-8")
    (out_dir / "design.json").write_text(dna.model_dump_json(indent=2), encoding="utf-8")

    console.print(f"[green]✓[/green] Study written to {out_dir}/design.md")
    console.print(f"  product_type={dna.product_type.value} density={dna.density.value} "
                  f"confidence={dna.confidence:.2f}")
    console.print(f"  {len(failures)} objective anti-pattern(s) detected")
    if not llm:
        console.print("[dim]  (heuristic/visual axes UNVERIFIED — rerun with --llm to judge)[/dim]")
    if export_json:
        # Sophia contract: the DesignDNA JSON is the LAST thing on stdout so
        # downstream agents can parse the trailing object without Hallmark.
        # soft_wrap + markup=False keep the JSON byte-exact (no rich wrapping
        # or bracket interpretation).
        console.print(
            dna.model_dump_json(indent=2), markup=False, highlight=False, soft_wrap=True
        )


def _enrich_with_llm(dna: DesignDNA, html: str) -> DesignDNA:
    """Ask the LLM judge to fill heuristic axes. Falls back to the deterministic
    DNA (confidence unchanged) if no provider is available — never fabricates."""
    try:
        from src.providers.llm.client import get_client

        client = get_client()
        prompt = (
            "You are a design analyst. Given this HTML, return ONLY a JSON object "
            "with keys: identity (one line), audience (one line), brand_character "
            "(list of 3-6 adjectives), interaction_language (one line), motion "
            "(one line). No prose.\n\nHTML:\n" + html[:6000]
        )
        data = client.generate_json(prompt)
        merged = dna.model_dump()
        for key in ("identity", "audience", "interaction_language", "motion"):
            if isinstance(data.get(key), str) and data[key].strip():
                merged[key] = data[key].strip()
        if isinstance(data.get("brand_character"), list):
            merged["brand_character"] = [str(x) for x in data["brand_character"]][:6]
        merged["confidence"] = 0.7
        return DesignDNA.model_validate(merged)
    except Exception as exc:  # noqa: BLE001 — LLM unavailable must not break study
        console.print(f"[yellow]⚠[/yellow] LLM judge unavailable ({exc}); keeping deterministic DNA")
        return dna


def run_redesign(study: str, out: str | None) -> None:
    src_dir = STUDIES_DIR / _slug(study)
    src_json = src_dir / "design.json"
    if not src_json.exists():
        console.print(f"[red]✗[/red] No study at {src_json}. Run `mekong ui study` first.")
        raise typer.Exit(1)

    dna = DesignDNA.model_validate(json.loads(src_json.read_text(encoding="utf-8")))
    # Preserve copy/IA/brand; change the fingerprint.
    redesigned = dna.model_copy(update={
        "identity": f"Redesign of: {dna.identity}",
        "macrostructure": _next_macrostructure(dna.macrostructure),
        "inspiration_sources": dna.inspiration_sources + [f"redesign-of:{_slug(study)}"],
    })

    out_dir = STUDIES_DIR / (_slug(out) if out else f"{_slug(study)}-v2")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "design.json").write_text(redesigned.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "design.md").write_text(
        _render_design_md(redesigned, f"redesign of {_slug(study)}", []), encoding="utf-8"
    )
    console.print(f"[green]✓[/green] Redesign written to {out_dir}/design.md")
    console.print(f"  macrostructure: {dna.macrostructure} → {redesigned.macrostructure}")


def _next_macrostructure(current: str | None) -> str:
    """Pick a different layout fingerprint so the redesign is not cosmetic."""
    options = [
        "asymmetric-split", "sidebar-workbench", "editorial-column",
        "card-grid", "single-focus-hero",
    ]
    if current in options:
        options.remove(current)
    return options[0]
