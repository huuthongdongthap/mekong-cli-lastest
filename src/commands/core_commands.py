# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Deprecated — legacy command definitions moved to canonical src.cli.app_setup.

Use `src.cli.app_setup.build_app()` instead.
"""

from __future__ import annotations

import warnings

from src.cli.app_setup import build_app

warnings.warn(
    "src.commands.core_commands is deprecated; use src.cli.app_setup.build_app() instead",
    DeprecationWarning,
    stacklevel=2,
)

app = build_app()

__all__ = ["app"]
