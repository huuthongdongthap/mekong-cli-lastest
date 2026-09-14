# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Pydantic v2 schemas for the Design Intelligence layer.

Covers the four core objects: DesignDNA (~21 axes), DesignBrief, AuditReport,
Theme. Product types span all archetypes the master command requires
(landing pages, SaaS dashboards, admin systems, AI workspaces, agent consoles,
trading terminals, ERP, CRM, content factories, mobile apps, data-heavy apps).

Schema derivation adapted from Hallmark's `study` verb (MIT) — rewritten as
typed data, not copied prompt text.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductType(StrEnum):
    """Product archetypes supported by `mekong ui` commands."""

    MARKETING_SITE = "marketing-site"
    LANDING_PAGE = "landing-page"
    SAAS_DASHBOARD = "saas-dashboard"
    ADMIN_CONSOLE = "admin-console"
    CRM = "crm"
    ERP = "erp"
    ANALYTICS = "analytics"  # data-heavy applications
    AI_WORKSPACE = "ai-workspace"
    AGENT_CONSOLE = "agent-console"
    TRADING_TERMINAL = "trading-terminal"
    CONTENT_FACTORY = "content-factory"
    ECOMMERCE = "ecommerce"
    MOBILE_APP = "mobile-app"
    DEVELOPER_TOOL = "developer-tool"
    DOCUMENTATION = "documentation"
    INTERNAL_TOOL = "internal-tool"


class Density(StrEnum):
    """Information density stance."""

    SPARSE = "sparse"
    COMFORTABLE = "comfortable"
    COMPACT = "compact"
    DENSE = "dense"


class Genre(StrEnum):
    """Design genre clusters (adapted from Hallmark's 4 genres)."""

    EDITORIAL = "editorial"
    MODERN_MINIMAL = "modern-minimal"
    ATMOSPHERIC = "atmospheric"
    PLAYFUL = "playful"


class EvidenceTier(StrEnum):
    """What evidence backs a finding. Never claim visual without rendering."""

    OBJECTIVE = "objective"  # static/deterministic check
    HEURISTIC = "heuristic"  # LLM judge or pattern inference
    OPINION = "opinion"  # design taste, explicitly flagged


class VisualQATier(StrEnum):
    """Level of visual evidence available for an audit."""

    FULL = "full"  # rendered + vision judge
    SCREENSHOT = "screenshot"  # rendered, no vision judge
    STATIC = "static"  # code-level analysis only


class DesignDNA(BaseModel):
    """Reusable design identity extracted by study or built from a brief.

    All optional axes default to None so partial studies (low confidence,
    limited evidence) stay valid; required axes enforce a usable minimum.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity axes
    identity: str = Field(..., min_length=1, description="One-line design identity statement")
    product_type: ProductType
    audience: str = Field(..., min_length=1, description="Who this is designed for")
    brand_character: list[str] = Field(default_factory=list, description="3-6 brand adjectives")

    # Structure axes
    macrostructure: str | None = Field(default=None, description="Named layout fingerprint")
    information_architecture: list[str] = Field(default_factory=list, description="Page/section order")

    # Typography axes
    typography: str | None = Field(default=None, description="Typographic stance")
    type_pairing: dict[str, str] = Field(default_factory=dict, description="role -> family")

    # Color axes
    color_system: str | None = Field(default=None, description="Palette approach (tokens, OKLCH...)")
    color_anchor: str | None = Field(default=None, description="Dominant anchor color")

    # Space & surface axes
    spacing: str | None = Field(default=None, description="Spacing rhythm description")
    density: Density = Density.COMFORTABLE
    surface_treatment: str | None = Field(default=None, description="Cards, borders, shadows stance")

    # Behavior axes
    interaction_language: str | None = Field(default=None)
    motion: str | None = Field(default=None, description="Motion stance, including reduced-motion")
    responsive_behavior: str | None = Field(default=None)

    # Content axes
    imagery: str | None = Field(default=None)
    iconography: str | None = Field(default=None)
    component_archetypes: list[str] = Field(default_factory=list)

    # Guard axes
    accessibility: list[str] = Field(default_factory=list, description="A11y commitments")
    anti_patterns: list[str] = Field(default_factory=list, description="Explicitly avoided patterns")
    inspiration_sources: list[str] = Field(default_factory=list, description="References, never clones")

    # Meta
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence 0-1")

    @field_validator("identity", "audience", "macrostructure")
    @classmethod
    def _strip_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if stripped == "":
            msg = "value must not be blank"
            raise ValueError(msg)
        return stripped


class DesignBrief(BaseModel):
    """Input brief for `mekong ui build` / pipeline entry."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    product_type: ProductType
    goal: str = Field(..., min_length=1, description="What the product must achieve")
    audience: str = Field(..., min_length=1)
    brand_constraints: list[str] = Field(default_factory=list)
    genre: Genre | None = Field(default=None, description="Inferred or explicit")
    platform: str = Field(default="web", description="web / mobile / desktop / embedded")
    tech_stack: list[str] = Field(default_factory=list)
    design_dna: DesignDNA | None = Field(default=None, description="Seed DNA if available")


class AuditFinding(BaseModel):
    """A single audit finding with explicit evidence classification."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=1)
    location: str | None = Field(default=None, description="File/selector if known")
    evidence: EvidenceTier
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Required for heuristic findings",
    )
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")

    @field_validator("confidence")
    @classmethod
    def _heuristic_needs_confidence(cls, v: float | None, info: object) -> float | None:
        data = getattr(info, "data", {})
        if data.get("evidence") == EvidenceTier.HEURISTIC and v is None:
            msg = "heuristic findings must expose a confidence value"
            raise ValueError(msg)
        return v


class AxisScores(BaseModel):
    """Nine scoring axes of the DESIGN SCORE block, each 0-100."""

    model_config = ConfigDict(extra="forbid")

    structure: int = Field(..., ge=0, le=100)
    typography: int = Field(..., ge=0, le=100)
    hierarchy: int = Field(..., ge=0, le=100)
    color: int = Field(..., ge=0, le=100)
    density: int = Field(..., ge=0, le=100)
    interaction: int = Field(..., ge=0, le=100)
    accessibility: int = Field(..., ge=0, le=100)
    distinctiveness: int = Field(..., ge=0, le=100)
    anti_slop: int = Field(..., ge=0, le=100)


class AuditReport(BaseModel):
    """Output of `mekong ui audit` — scores, failures, and evidence tiers."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(..., min_length=1)
    visual_qa_tier: VisualQATier
    scores: AxisScores
    critical_failures: list[str] = Field(default_factory=list)
    recommended_fixes: list[str] = Field(default_factory=list)
    findings: list[AuditFinding] = Field(default_factory=list)


class Theme(BaseModel):
    """A named theme: palette anchor, fonts, diversification axes."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    genre: Genre
    anchor_color: str = Field(..., min_length=1, description="Named token or color value")
    surface: str | None = Field(default=None, description="Paper/band treatment")
    display_font: str | None = None
    body_font: str | None = None
    diversification_notes: list[str] = Field(
        default_factory=list,
        description="Axes that differ from the last 3 used themes",
    )
