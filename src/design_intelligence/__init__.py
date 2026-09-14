# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Mekong Design Intelligence layer.

Native design-quality system adapted from Hallmark (github.com/nutlope/hallmark,
MIT) — structured schemas, deterministic gates, and a reusable Design DNA model
instead of prompt-only knowledge. See docs/design-intelligence.md.
"""

from src.design_intelligence.schemas import (
    AuditReport,
    DesignBrief,
    DesignDNA,
    ProductType,
    Theme,
)

__all__ = [
    "AuditReport",
    "DesignBrief",
    "DesignDNA",
    "ProductType",
    "Theme",
]