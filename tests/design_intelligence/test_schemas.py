# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Schema validation tests for the Design Intelligence layer.

Real Pydantic validation only — no mocks. Acceptance: a landing-page DNA and
a trading-dashboard DNA must validate; invalid payloads must fail loudly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.design_intelligence.schemas import DesignDNA, ProductType


def landing_page_dna() -> dict:
    return {
        "identity": "Warm editorial landing page for a Vietnamese coffee brand",
        "product_type": "landing-page",
        "audience": "Urban Vietnamese consumers aged 25-40",
        "brand_character": ["warm", "artisanal", "confident"],
        "macrostructure": "Hero -> story band -> product grid -> testimonials -> CTA",
        "information_architecture": ["hero", "story", "products", "testimonials", "cta"],
        "typography": "Large serif display over clean sans body",
        "type_pairing": {"display": "Fraunces", "body": "Inter"},
        "color_system": "OKLCH tokens, cream base with espresso anchor",
        "color_anchor": "oklch(0.35 0.08 45)",
        "spacing": "Generous 8px grid, airy sections",
        "density": "sparse",
        "surface_treatment": "Soft paper cards, hairline borders, no heavy shadows",
        "interaction_language": "Subtle hover lifts, no parallax",
        "motion": "Fade-up on scroll, respects prefers-reduced-motion",
        "responsive_behavior": "Single column below 768px, sticky CTA",
        "imagery": "Natural-light product photography",
        "iconography": "Thin-line icons only",
        "component_archetypes": ["hero", "feature-card", "testimonial", "cta-band"],
        "accessibility": ["WCAG AA contrast", "focus-visible rings"],
        "anti_patterns": ["gradient text", "glassmorphism"],
        "inspiration_sources": ["Aesop", "Blue Bottle"],
        "confidence": 0.85,
    }


def trading_dashboard_dna() -> dict:
    return {
        "identity": "High-density dark trading terminal for professional traders",
        "product_type": "trading-terminal",
        "audience": "Professional day traders running multi-monitor setups",
        "brand_character": ["precise", "fast", "technical"],
        "macrostructure": "Watchlist rail -> chart canvas -> order ticket -> blotter",
        "information_architecture": ["watchlist", "chart", "order-ticket", "blotter"],
        "typography": "Tabular numerals, compact sans throughout",
        "type_pairing": {"body": "IBM Plex Mono", "ui": "Inter"},
        "color_system": "Dark token set, green/red semantic only",
        "color_anchor": "#0b0e14",
        "spacing": "4px grid, minimal padding",
        "density": "dense",
        "surface_treatment": "Flat panels, 1px borders, zero shadows",
        "interaction_language": "Keyboard-first, instant feedback",
        "motion": "None except price-flash highlights",
        "responsive_behavior": "Fixed desktop layout, panels collapse to tabs",
        "imagery": "None — charts only",
        "iconography": "Monochrome 16px glyphs",
        "component_archetypes": ["data-table", "chart", "order-form", "ticker"],
        "accessibility": ["AA contrast on dark", "keyboard navigation"],
        "anti_patterns": ["decorative gradients", "rounded-everything"],
        "inspiration_sources": ["Bloomberg Terminal", "TradingView"],
        "confidence": 0.9,
    }


class TestAcceptanceSamples:
    def test_landing_page_dna_validates(self) -> None:
        dna = DesignDNA.model_validate(landing_page_dna())
        assert dna.product_type is ProductType.LANDING_PAGE
        assert dna.identity.startswith("Warm editorial")
        assert dna.confidence == pytest.approx(0.85)

    def test_trading_dashboard_dna_validates(self) -> None:
        dna = DesignDNA.model_validate(trading_dashboard_dna())
        assert dna.product_type is ProductType.TRADING_TERMINAL
        assert dna.density.value == "dense"
        assert dna.type_pairing["body"] == "IBM Plex Mono"

    def test_minimal_dna_validates_with_defaults(self) -> None:
        dna = DesignDNA.model_validate(
            {
                "identity": "Minimal internal tool",
                "product_type": "internal-tool",
                "audience": "Ops team",
                "confidence": 0.5,
            }
        )
        assert dna.macrostructure is None
        assert dna.brand_character == []
        assert dna.density.value == "comfortable"


class TestInvalidInput:
    def test_confidence_above_one_rejected(self) -> None:
        data = landing_page_dna()
        data["confidence"] = 1.5
        with pytest.raises(ValidationError, match="confidence"):
            DesignDNA.model_validate(data)

    def test_negative_confidence_rejected(self) -> None:
        data = landing_page_dna()
        data["confidence"] = -0.1
        with pytest.raises(ValidationError, match="confidence"):
            DesignDNA.model_validate(data)

    def test_blank_identity_rejected(self) -> None:
        data = landing_page_dna()
        data["identity"] = "   "
        with pytest.raises(ValidationError, match="identity"):
            DesignDNA.model_validate(data)

    def test_blank_audience_rejected(self) -> None:
        data = landing_page_dna()
        data["audience"] = ""
        with pytest.raises(ValidationError, match="audience"):
            DesignDNA.model_validate(data)

    def test_unknown_product_type_rejected(self) -> None:
        data = landing_page_dna()
        data["product_type"] = "crypto-casino"
        with pytest.raises(ValidationError, match="product_type"):
            DesignDNA.model_validate(data)

    def test_extra_field_rejected(self) -> None:
        data = landing_page_dna()
        data["vibe_check"] = "immaculate"
        with pytest.raises(ValidationError, match="vibe_check"):
            DesignDNA.model_validate(data)

    def test_missing_required_field_rejected(self) -> None:
        data = landing_page_dna()
        del data["audience"]
        with pytest.raises(ValidationError, match="audience"):
            DesignDNA.model_validate(data)
