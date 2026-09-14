# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.
"""
Design tokens for Mekong CLI.

Single source of truth for M3/Palette-wannabe colors used by both
the Rich terminal theme (cli/theme.py) and any JSON-exported config
that web/React code can consume.

Tokens are plain strings — no framework coupling.
"""
from rich.style import Style
from rich.theme import Theme

# ── Material Design 3 palette (approximated for terminal) ──────────────
# Primary: Violet family (matches product branding)
PRIMARY = "#A78BFA"  # Violet-400
PRIMARY_DARK = "#8B5CF6"  # Violet-500
PRIMARY_LIGHT = "#C4B5FD"  # Violet-300

# Secondary: Teal family (complementary cool accent)
SECONDARY = "#2DD4BF"  # Teal-400
SECONDARY_DARK = "#14B8A6"  # Teal-500

# Semantic colors
SUCCESS = "#34D399"  # Emerald-400
WARNING = "#FBBF24"  # Amber-400
ERROR = "#F87171"  # Red-400
INFO = "#60A5FA"  # Blue-400

# Neutral scale
WHITE = "#FFFFFF"
DIM = "#737373"  # Neutral-500
SURFACE = "#171717"  # Neutral-900 (dark bg)
PANEL_BORDER = "#374151"  # Gray-700
PANEL_BG = "#0F0F0F"

# Accent / highlight
HIGHLIGHT = "#FACC15"  # Yellow-400
COMMAND = "#A78BFA italic"  # Violet italic

# ── Token export (dict for JSON serialization) ─────────────────────────
def get_theme() -> Theme:
    """Return the Rich Theme built from design tokens."""
    return Theme({k: Style.parse(v) for k, v in TOKENS.items()})


TOKENS = {
    "primary": PRIMARY,
    "primaryDark": PRIMARY_DARK,
    "primaryLight": PRIMARY_LIGHT,
    "secondary": SECONDARY,
    "secondaryDark": SECONDARY_DARK,
    "success": SUCCESS,
    "warning": WARNING,
    "error": ERROR,
    "info": INFO,
    "white": WHITE,
    "dim": DIM,
    "surface": SURFACE,
    "panelBorder": PANEL_BORDER,
    "panelBg": PANEL_BG,
    "highlight": HIGHLIGHT,
}
