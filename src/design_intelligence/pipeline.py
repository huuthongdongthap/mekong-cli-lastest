# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.
# Adapted from Hallmark's macrostructure catalog (github.com/nutlope/hallmark, MIT).

"""Selection pipeline: archetype + brief -> macrostructure + theme.

`mekong ui build` takes a DesignDNA. This module turns a DesignBrief into a
DesignDNA by consulting the archetype spec and the macrostructure catalog:

  1. load the archetype for the brief's product_type
  2. filter macrostructures to those the archetype allows
  3. rank by how well the macro fits the brief (product_type, genre, density)
  4. pick the top-ranked macrostructure (deterministic, seeded by the brief)

The ranking is deterministic and brief-seeded, so two different briefs pick
different macrostructures — the variety requirement. No LLM is needed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from src.design_intelligence.schemas import (
    Density,
    DesignBrief,
    DesignDNA,
    ProductType,
)

_KNOWN = Path(__file__).resolve().parent / "knowledge"

_ARCHETYPES: dict[str, dict[str, Any]] | None = None
_MACROS: list[dict[str, Any]] | None = None


def _load_archetypes() -> dict[str, dict[str, Any]]:
    global _ARCHETYPES
    if _ARCHETYPES is None:
        out: dict[str, dict[str, Any]] = {}
        for path in sorted((_KNOWN / "archetypes").glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            out[str(data["id"])] = data
        _ARCHETYPES = out
    return _ARCHETYPES


def _load_macros() -> list[dict[str, Any]]:
    global _MACROS
    if _MACROS is None:
        data = yaml.safe_load((_KNOWN / "macros.yaml").read_text(encoding="utf-8"))
        _MACROS = list(data["macros"])
    return _MACROS


def archetype_for(product_type: ProductType) -> dict[str, Any]:
    """Return the archetype spec for a product type. Raises if unknown."""
    arch = _load_archetypes().get(product_type.value)
    if arch is None:
        msg = f"no archetype spec for product_type={product_type.value!r}"
        raise KeyError(msg)
    return arch


def select_macrostructure(brief: DesignBrief) -> str:
    """Pick the best macrostructure for a brief from the archetype's allowed set.

    Ranking: each allowed macro scores +3 per product_type in its best_for,
    +1 per genre match, +1 if the macro's density stance aligns with the brief.
    Ties break by catalog order (deterministic). The brief's name is mixed in
    as a stable seed so distinct briefs land on distinct fingerprints.
    """
    arch = archetype_for(brief.product_type)
    allowed = set(arch.get("appropriate_macrostructures", []))
    if not allowed:
        # No archetype restriction — fall back to the whole catalog.
        allowed = {m["id"] for m in _load_macros()}

    genre = brief.genre.value if brief.genre else None
    brief_words = set(re.findall(r"[a-z]+", brief.name.lower()))
    brief_words |= set(re.findall(r"[a-z]+", brief.goal.lower()))

    scored: list[tuple[int, int, str]] = []
    for idx, macro in enumerate(_load_macros()):
        mid = str(macro["id"])
        if mid not in allowed:
            continue
        score = 0
        best_for = [str(x) for x in macro.get("best_for", [])]
        avoid = [str(x) for x in macro.get("avoid", [])]
        score += 3 * best_for.count(brief.product_type.value)
        if genre and genre in best_for:
            score += 1
        # A macro that avoids the brief's product type is disqualified.
        if brief.product_type.value in avoid:
            score -= 20
        # Brief-name words that echo the macro's summary give a small nudge.
        summary_words = set(re.findall(r"[a-z]+", str(macro.get("summary", "")).lower()))
        score += 1 * len(brief_words & summary_words)
        scored.append((score, idx, mid))

    if not scored:
        msg = f"no macrostructure available for product_type={brief.product_type.value!r}"
        raise ValueError(msg)

    # Highest score first; ties broken by catalog order (idx) for determinism.
    scored.sort(key=lambda t: (-t[0], t[1]))
    return scored[0][2]


def _density_for(brief: DesignBrief) -> Density:
    arch = archetype_for(brief.product_type)
    raw = arch.get("information_density")
    if raw is None:
        return Density.COMFORTABLE
    try:
        return Density(raw)
    except ValueError:
        return Density.COMFORTABLE


def build_dna(brief: DesignBrief, *, seed: str | None = None) -> DesignDNA:
    """Turn a DesignBrief into a DesignDNA for `mekong ui build`.

    The macrostructure is selected by archetype + brief (see
    select_macrostructure). All other axes come from the brief's design_dna
    if present, otherwise from the archetype spec.
    """
    if brief.design_dna is not None:
        dna = brief.design_dna
    else:
        arch = archetype_for(brief.product_type)
        dna = DesignDNA(
            identity=f"{brief.name} — {brief.goal[:80]}",
            product_type=brief.product_type,
            audience=brief.audience,
            brand_character=list(brief.brand_constraints)[:6],
            macrostructure=select_macrostructure(brief),
            information_architecture=[],
            typography=None,
            type_pairing={},
            color_system=None,
            color_anchor=None,
            spacing=None,
            density=_density_for(brief),
            surface_treatment=None,
            interaction_language=None,
            motion=None,
            responsive_behavior=None,
            imagery=None,
            iconography=None,
            component_archetypes=[],
            accessibility=[],
            anti_patterns=list(arch.get("common_failure_modes", []))[:4],
            inspiration_sources=[],
            confidence=0.7,
        )
    # Ensure the macrostructure is always brief-selected, never inherited stale.
    return dna.model_copy(update={"macrostructure": select_macrostructure(brief)})