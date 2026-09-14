# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Pipeline tests: archetype catalog + brief-seeded macrostructure selection.

Acceptance (plan Bước 4):
  - every ProductType has an archetype spec with all 8 spec attributes
  - two different briefs select different macrostructures (variety requirement)
  - a brief that names an avoided macrostructure never selects it
"""

from __future__ import annotations

from src.design_intelligence.pipeline import (
    _load_archetypes,
    _load_macros,
    archetype_for,
    build_dna,
    select_macrostructure,
)
from src.design_intelligence.schemas import (
    DesignBrief,
    Density,
    Genre,
    ProductType,
)

_REQUIRED = (
    "summary",
    "information_density",
    "navigation_patterns",
    "hierarchy",
    "interaction_expectations",
    "common_failure_modes",
    "accessibility_concerns",
    "responsive_requirements",
    "appropriate_macrostructures",
)


def test_every_product_type_has_an_archetype() -> None:
    """16 ProductType values, 16 archetype YAMLs, all 9 spec attributes present."""
    archetypes = _load_archetypes()
    assert len(archetypes) == len(list(ProductType)), (
        f"expected {len(list(ProductType))} archetypes, got {len(archetypes)}"
    )
    for product_type in ProductType:
        arch = archetype_for(product_type)
        missing = [k for k in _REQUIRED if k not in arch]
        assert not missing, f"{product_type.value} missing {missing}"
        assert arch["id"] == product_type.value
        assert len(arch["appropriate_macrostructures"]) >= 1


def test_all_macros_load_with_best_for_and_avoid() -> None:
    macros = _load_macros()
    assert len(macros) >= 21
    for m in macros:
        assert "id" in m and "summary" in m
        assert "best_for" in m and "avoid" in m


def test_two_different_briefs_select_different_macros() -> None:
    """Variety requirement: distinct briefs must not all collapse to one layout."""
    a = DesignBrief(
        name="Acme Sales CRM",
        product_type=ProductType.CRM,
        goal="Track every deal and follow-up in one screen",
        audience="sales team",
        genre=Genre.EDITORIAL,
    )
    b = DesignBrief(
        name="Pulse Trading Terminal",
        product_type=ProductType.TRADING_TERMINAL,
        goal="Real-time positions and risk at a glance",
        audience="prop traders",
        genre=Genre.ATMOSPHERIC,
    )
    ma = select_macrostructure(a)
    mb = select_macrostructure(b)
    assert ma != mb, f"variety requirement failed: both briefs picked {ma!r}"


def test_brief_never_selects_an_avoided_macro() -> None:
    """A macrostructure that the archetype explicitly avoids is disqualified."""
    brief = DesignBrief(
        name="Launch Page",
        product_type=ProductType.LANDING_PAGE,
        goal="One message, one audience, one CTA",
        audience="visitors",
    )
    avoided = {m["id"] for m in _load_macros() if "landing-page" in m.get("avoid", [])}
    chosen = select_macrostructure(brief)
    assert chosen not in avoided, f"chosen {chosen!r} is explicitly avoided by the archetype"


def test_build_dna_uses_brief_selected_macrostructure() -> None:
    """`mekong ui build` from a brief always carries a brief-selected macro."""
    brief = DesignBrief(
        name="Orbit Analytics",
        product_type=ProductType.ANALYTICS,
        goal="Decision-first metrics above the fold",
        audience="product lead",
        genre=Genre.MODERN_MINIMAL,
    )
    dna = build_dna(brief)
    assert dna.macrostructure == select_macrostructure(brief)
    assert dna.product_type == ProductType.ANALYTICS
    assert dna.density == Density.COMFORTABLE


def test_select_macrostructure_is_deterministic() -> None:
    """Same brief always yields the same macrostructure (no randomness)."""
    brief = DesignBrief(
        name="Stable Brief",
        product_type=ProductType.ERP,
        goal="Record entry and module navigation",
        audience="ops team",
    )
    first = select_macrostructure(brief)
    for _ in range(5):
        assert select_macrostructure(brief) == first


def test_internal_tool_archetype_loads() -> None:
    """The 16th archetype (internal-tool) is present and usable."""
    arch = archetype_for(ProductType.INTERNAL_TOOL)
    assert arch["label"] == "Internal tool"
    assert "form-workbench" in arch["appropriate_macrostructures"]