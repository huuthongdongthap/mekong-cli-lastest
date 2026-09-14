# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
Backward-compatible re-export façade for Tier configuration.

Canonical implementation lives in src.seed.config.tiers.
This façade forwards all imports to preserve API/ABI compatibility.
"""
from __future__ import annotations

from src.seed.config.tiers import (
    DEFAULT_TIER_CONFIGS,
    RateLimitConfig,
    Tier,
    TierKey,
    TierRateLimitConfig,
    get_preset_config,
    get_tier_config,
)

__all__ = [
    "Tier",
    "TierKey",
    "RateLimitConfig",
    "TierRateLimitConfig",
    "DEFAULT_TIER_CONFIGS",
    "get_tier_config",
    "get_preset_config",
]
