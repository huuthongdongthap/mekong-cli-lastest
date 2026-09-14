# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Unified Tier Config — single source of truth for all tier/pricing/credit data.

This module consolidates the three previously-divergent tier vocabularies:

1. MCU billing tiers   : starter / growth / premium (mcu_billing.py)
2. VN product tiers    : starter_vn / growth_vn / pro_vn (pricing.json)
3. Documentation tiers : Starter / Growth / Pro (CLAUDE.md)

Each tier has a unqiue canonical key. Backward-compatible aliases are provided
for every historical name so existing callers keep working.

Usage:
    from src.seed.config.tiers import TierConfig, get_tier, tier_credits
    tier = get_tier("growth")           # returns TierConfig
    credits = tier_credits("growth")    # 200
    credits = tier_credits("TRIAL")     # 50  (alias works)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union


# =================================================================--
# Canonical tier enum — tier key constants used everywhere going forward
# =================================================================--

class TierKey(Enum):
    """Unique identifier for each pricing tier.

    These are the canonical keys. All other tier names are aliases.
    """

    FREE = "free"
    TRIAL = "trial"
    STARTER = "starter"
    GROWTH = "growth"
    PRO = "pro"
    ENTERPRISE = "enterprise"

    @classmethod
    def values(cls) -> list[str]:
        return [t.value for t in cls]

    @classmethod
    def aliases(cls) -> dict[str, str]:
        """Return every historical tier name → canonical key mapping."""
        return {
            # free tier synonyms
            "free": "free",
            "FREE": "free",
            # trial synonyms
            "trial": "trial",
            "trial_vn": "trial",
            "TRIAL": "trial",
            # starter synonyms
            "starter": "starter",
            "starter_vn": "starter",
            "basic": "starter",
            "BASIC": "starter",
            "STARTER": "starter",
            # growth synonyms
            "growth": "growth",
            "growth_vn": "growth",
            "PREMIUM": "growth",  # legacy mcu_billing "premium" = growth
            "premium": "growth",
            "GROWTH": "growth",
            "team": "growth",     # legacy raas/pricing.py "team"
            "TEAM": "growth",
            # pro synonyms
            "pro": "pro",
            "pro_vn": "pro",
            "enterprise": "pro",  # some systems treat pro/enterprise as same
            "ENTERPRISE": "pro",
            "PRO": "pro",
            "MASTER": "pro",      # Sophia tier
            "master": "pro",
            # enterprise (true enterprise)
            "enterprise_plus": "enterprise",
        }

    @classmethod
    def _missing_(cls, value: object):
        """Resolve case-insensitive names and legacy aliases on instantiation."""
        if isinstance(value, str):
            val_lower = value.lower()
            for member in cls:
                if member.value == val_lower:
                    return member
            canonical = cls.aliases().get(value) or cls.aliases().get(val_lower)
            if canonical:
                for member in cls:
                    if member.value == canonical:
                        return member
        return None


# Tier is the canonical alias for TierKey, providing seamless backward-compatibility
# for consumers expecting Tier enum (such as engine.license.license_enforcer).
Tier = TierKey


# ===================================================================
# TierConfig — complete definition of a single tier
# ===================================================================

@dataclass(frozen=True)
class TierConfig:
    """Immutable definition of a pricing tier.

    Attributes:
        key: Canonical tier key (TierKey.value).
        display_name: Human name. Example: "Growth".
        display_name_vi: Vietnamese name. Example: "Tăng trưởng".
        monthly_credits: MCU credits per billing period.
        monthly_price_usd: Monthly price in USD. 0 for free/trial.
        monthly_price_vnd: Monthly price in VND (primary VN market).
        mcu_cost_simple: Cost for simple task complexity (default 1).
        mcu_cost_standard: Cost for standard task complexity (default 3).
        mcu_cost_complex: Cost for complex task complexity (default 5).
        daily_command_limit: Max commands/day. 0 = unlimited.
        daily_agent_limit: Max agent calls/day. 0 = unlimited.
        daily_pipeline_limit: Max pipeline runs/day. 0 = unlimited.
        trial_days: Days before trial expires. 0 = no trial.
        grace_days: Days after trial expiry before downgrade.
        features: List of enabled feature IDs.
    """

    key: str
    display_name: str = ""
    display_name_vi: str = ""
    monthly_credits: int = 0
    monthly_price_usd: float = 0.0
    monthly_price_vnd: int = 0
    mcu_cost_simple: int = 1
    mcu_cost_standard: int = 3
    mcu_cost_complex: int = 5
    daily_command_limit: int = 0
    daily_agent_limit: int = 0
    daily_pipeline_limit: int = 0
    trial_days: int = 0
    grace_days: int = 0
    features: tuple[str, ...] = ()


# ===================================================================
# Tier definitions — edit only here to change pricing/features across the app
# ===================================================================

_TIERS: dict[str, TierConfig] = {
    "free": TierConfig(
        key="free",
        display_name="Free",
        display_name_vi="Miễn phí",
        monthly_credits=10,
        monthly_price_usd=0,
        monthly_price_vnd=0,
        daily_command_limit=10,
        daily_agent_limit=5,
        daily_pipeline_limit=3,
        features=("cli_commands",),
    ),
    "trial": TierConfig(
        key="trial",
        display_name="Trial",
        display_name_vi="Dùng thử",
        monthly_credits=50,
        monthly_price_usd=0,
        monthly_price_vnd=0,
        trial_days=14,
        grace_days=3,
        features=("cli_commands", "basic_agents"),
    ),
    "starter": TierConfig(
        key="starter",
        display_name="Starter",
        display_name_vi="Starter",
        monthly_credits=200,
        monthly_price_usd=49,
        monthly_price_vnd=199_000,
        features=("cli_commands", "advanced_agents", "gateway_integration"),
        # matches CLAUDE.md: Starter = 200 credits, $49
    ),
    "growth": TierConfig(
        key="growth",
        display_name="Growth",
        display_name_vi="Tăng trưởng",
        monthly_credits=1000,
        monthly_price_usd=149,
        monthly_price_vnd=299_000,
        features=("cli_commands", "advanced_agents", "gateway_integration", "kv_store_sync"),
        # matches CLAUDE.md: Growth = 1000 credits, $149
    ),
    "pro": TierConfig(
        key="pro",
        display_name="Pro",
        display_name_vi="Professional",
        monthly_credits=5000,
        monthly_price_usd=499,
        monthly_price_vnd=499_000,
        features=(
            "cli_commands",
            "advanced_agents",
            "gateway_integration",
            "kv_store_sync",
            "real_time_entitlements",
            "enterprise_features",
        ),
        # matches CLAUDE.md: Pro = 5000 credits, $499
    ),
    "enterprise": TierConfig(
        key="enterprise",
        display_name="Enterprise",
        display_name_vi="Doanh nghiệp",
        monthly_credits=20_000,
        monthly_price_usd=0,   # custom pricing
        monthly_price_vnd=0,   # custom pricing
        features=(
            "cli_commands",
            "advanced_agents",
            "gateway_integration",
            "kv_store_sync",
            "real_time_entitlements",
            "enterprise_features",
        ),
    ),
}


# ===================================================================
# Lookup helpers — backward-compatible entry points
# ===================================================================

def _resolve(key_or_alias: str) -> str | None:
    """Resolve any tier name (canonical or alias) to canonical key."""
    if not key_or_alias:
        return None
    aliases = TierKey.aliases()
    canonical = aliases.get(key_or_alias.lower())
    if canonical:
        return canonical
    # Direct canonical match
    if key_or_alias in _TIERS:
        return key_or_alias
    return None


def get_tier(key_or_alias: str) -> TierConfig | None:
    """Return TierConfig for any tier name (canonical or alias).

    Args:
        key_or_alias: Any known tier name (case-insensitive alias or canonical key).

    Returns:
        TierConfig if found, None otherwise.
    """
    resolved = _resolve(key_or_alias)
    return _TIERS.get(resolved) if resolved else None


def tier_credits(key_or_alias: str, default: int = 0) -> int:
    """Return monthly_credits for any tier name (canonical or alias).

    Args:
        key_or_alias: Any known tier name.
        default: Fallback value if tier not found.

    Returns:
        Monthly credit allocation. Default if unknown tier.
    """
    tier = get_tier(key_or_alias)
    return tier.monthly_credits if tier else default


def tier_features(key_or_alias: str) -> tuple[str, ...]:
    """Return enabled feature IDs for a tier.

    Args:
        key_or_alias: Any known tier name.

    Returns:
        Tuple of feature ID strings. Empty tuple if tier not found.
    """
    tier = get_tier(key_or_alias)
    return tier.features if tier else ()


def mcu_cost(key_or_alias: str, complexity: str) -> int:
    """Return MCU cost for a given complexity level under a tier.

    Args:
        key_or_alias: Any known tier name.
        complexity: One of 'simple', 'standard', 'complex'.

    Returns:
        MCU cost integer. 1 if tier not found or unknown complexity.
    """
    tier = get_tier(key_or_alias)
    if not tier:
        return 1
    cost_map = {
        "simple": tier.mcu_cost_simple,
        "standard": tier.mcu_cost_standard,
        "complex": tier.mcu_cost_complex,
    }
    return cost_map.get(complexity, 1)


# ===================================================================
# Backward-compatible dict aliases — code that expects dicts keeps working
# ===================================================================

def tier_credits_dict() -> dict[str, int]:
    """Return TIER_CREDITS dict keyed by canonical tier key.

    Maintains ABI compatibility with src.core.mcu_billing.TIERER_CREDITS
    which used: starter:50, growth:200, premium:1000.
    """
    return {k: v.monthly_credits for k, v in _TIERS.items()
            if k not in ("free", "enterprise")}


def mcu_costs_dict() -> dict[str, int]:
    """Return MCU_COSTS dict — backward-compatible with mcu_billing.MCU_COSTS."""
    t = _TIERS["starter"]
    return {
        "simple": t.mcu_cost_simple,
        "standard": t.mcu_cost_standard,
        "complex": t.mcu_cost_complex,
    }


# ===================================================================
# Quota enforcement data (replaces FREE_TIER_LIMITS from usage_tracker.py)
# ===================================================================

@dataclass(frozen=True)
class TierQuotas:
    """Daily quotas for a tier."""

    commands: int = 0
    agents: int = 0
    pipelines: int = 0


def tier_quotas(key_or_alias: str) -> TierQuotas:
    """Return daily quotas for a tier.

    Args:
        key_or_alias: Any known tier name.

    Returns:
        TierQuotas with 0 = unlimited for paid tiers.
    """
    tier = get_tier(key_or_alias)
    if not tier:
        return TierQuotas()
    return TierQuotas(
        commands=tier.daily_command_limit,
        agents=tier.daily_agent_limit,
        pipelines=tier.daily_pipeline_limit,
    )


# ===================================================================
# VN-market helpers (integration with factory/contracts/pricing.json)
# ===================================================================

def vn_tier_for_pricing_file(key_or_alias: str) -> str | None:
    """Map canonical tier key to pricing.json vn_products key.

    Used to bridge this module with factory/contracts/pricing.json for VN
    price display.
    """
    tier = get_tier(key_or_alias)
    if not tier:
        return None
    mapping = {
        "free": None,
        "trial": None,
        "starter": "starter_vn",
        "growth": "growth_vn",
        "pro": "pro_vn",
        "enterprise": None,
    }
    return mapping.get(tier.key)


# ===================================================================
# Trial helpers
# ===================================================================

def trial_config(key_or_alias: str) -> tuple[int, int] | None:
    """Return (trial_days, grace_days) if tier has a trial.

    Returns:
        (trial_days, grace_days) tuple, or None if no trial.
    """
    tier = get_tier(key_or_alias)
    if not tier or tier.trial_days == 0:
        return None
    return (tier.trial_days, tier.grace_days)


# ===================================================================
# Rate Limiting Configuration (migrated from engine.billing.tier_config)
# ===================================================================

@dataclass
class RateLimitConfig:
    """Rate limit configuration for a single endpoint."""
    requests_per_minute: int
    burst_size: Optional[int] = None  # Token bucket burst size (default = rpm)
    window_seconds: Optional[int] = None  # Time window in seconds (default: 60)

    def __post_init__(self) -> None:
        if self.burst_size is None:
            self.burst_size = self.requests_per_minute
        if self.window_seconds is None:
            self.window_seconds = 60


@dataclass
class TierRateLimitConfig:
    """Complete rate limit configuration for a tier."""
    tier: TierKey
    auth_login: RateLimitConfig
    auth_callback: RateLimitConfig
    auth_refresh: RateLimitConfig
    api_default: RateLimitConfig


# Default tier configurations supporting all canonical tiers
DEFAULT_TIER_CONFIGS: dict[TierKey, TierRateLimitConfig] = {
    TierKey.FREE: TierRateLimitConfig(
        tier=TierKey.FREE,
        auth_login=RateLimitConfig(requests_per_minute=5, burst_size=5),
        auth_callback=RateLimitConfig(requests_per_minute=10, burst_size=10),
        auth_refresh=RateLimitConfig(requests_per_minute=10, burst_size=10),
        api_default=RateLimitConfig(requests_per_minute=20, burst_size=30),
    ),
    TierKey.TRIAL: TierRateLimitConfig(
        tier=TierKey.TRIAL,
        auth_login=RateLimitConfig(requests_per_minute=10, burst_size=10),
        auth_callback=RateLimitConfig(requests_per_minute=20, burst_size=20),
        auth_refresh=RateLimitConfig(requests_per_minute=20, burst_size=20),
        api_default=RateLimitConfig(requests_per_minute=40, burst_size=60),
    ),
    TierKey.STARTER: TierRateLimitConfig(
        tier=TierKey.STARTER,
        auth_login=RateLimitConfig(requests_per_minute=15, burst_size=15),
        auth_callback=RateLimitConfig(requests_per_minute=30, burst_size=30),
        auth_refresh=RateLimitConfig(requests_per_minute=30, burst_size=30),
        api_default=RateLimitConfig(requests_per_minute=50, burst_size=75),
    ),
    TierKey.GROWTH: TierRateLimitConfig(
        tier=TierKey.GROWTH,
        auth_login=RateLimitConfig(requests_per_minute=20, burst_size=20),
        auth_callback=RateLimitConfig(requests_per_minute=45, burst_size=45),
        auth_refresh=RateLimitConfig(requests_per_minute=45, burst_size=45),
        api_default=RateLimitConfig(requests_per_minute=80, burst_size=120),
    ),
    TierKey.PRO: TierRateLimitConfig(
        tier=TierKey.PRO,
        auth_login=RateLimitConfig(requests_per_minute=30, burst_size=30),
        auth_callback=RateLimitConfig(requests_per_minute=60, burst_size=60),
        auth_refresh=RateLimitConfig(requests_per_minute=60, burst_size=60),
        api_default=RateLimitConfig(requests_per_minute=100, burst_size=150),
    ),
    TierKey.ENTERPRISE: TierRateLimitConfig(
        tier=TierKey.ENTERPRISE,
        auth_login=RateLimitConfig(requests_per_minute=100, burst_size=100),
        auth_callback=RateLimitConfig(requests_per_minute=200, burst_size=200),
        auth_refresh=RateLimitConfig(requests_per_minute=200, burst_size=200),
        api_default=RateLimitConfig(requests_per_minute=500, burst_size=750),
    ),
}


def get_tier_config(tier: Union[str, TierKey]) -> TierRateLimitConfig:
    """
    Get rate limit configuration for a tier.

    Args:
        tier: Tier name or Tier/TierKey enum value

    Returns:
        TierRateLimitConfig for the specified tier

    Raises:
        ValueError: If tier is not recognized
    """
    if isinstance(tier, str):
        try:
            tier_enum = TierKey(tier)
        except ValueError:
            raise ValueError(f"Invalid tier: {tier}. Must be one of: {[t.value for t in TierKey]}")
    elif isinstance(tier, TierKey):
        tier_enum = tier
    else:
        raise ValueError(f"Invalid tier: {tier}. Must be one of: {[t.value for t in TierKey]}")

    if tier_enum not in DEFAULT_TIER_CONFIGS:
        raise ValueError(f"Invalid tier: {tier}. Must be one of: {[t.value for t in TierKey]}")

    return DEFAULT_TIER_CONFIGS[tier_enum]


def get_preset_config(tier: Union[str, TierKey], preset: str) -> RateLimitConfig:
    """
    Get rate limit config for a specific preset endpoint.

    Args:
        tier: Tier name or Tier/TierKey enum
        preset: Preset name (auth_login, auth_callback, auth_refresh, api_default)

    Returns:
        RateLimitConfig for the preset

    Raises:
        ValueError: If tier or preset is invalid
    """
    tier_config = get_tier_config(tier)

    preset_map = {
        "auth_login": tier_config.auth_login,
        "auth_callback": tier_config.auth_callback,
        "auth_refresh": tier_config.auth_refresh,
        "api_default": tier_config.api_default,
    }

    if preset not in preset_map:
        raise ValueError(
            f"Invalid preset: {preset}. Must be one of: {list(preset_map.keys())}"
        )

    return preset_map[preset]


# ===================================================================
# Public API
# ===================================================================

__all__ = [
    # Core types
    "Tier",
    "TierKey",
    "TierConfig",
    "TierQuotas",
    "RateLimitConfig",
    "TierRateLimitConfig",
    "DEFAULT_TIER_CONFIGS",
    # All tier configs keyed by canonical key
    "_TIERS",
    # Lookup functions
    "get_tier",
    "tier_credits",
    "tier_features",
    "mcu_cost",
    "tier_quotas",
    "trial_config",
    "get_tier_config",
    "get_preset_config",
    # Backward-compat dicts
    "tier_credits_dict",
    "mcu_costs_dict",
    # VN bridging
    "vn_tier_for_pricing_file",
]


def _demo() -> None:
    """Quick sanity check — run this module directly."""

    print(f"Tier config loaded. {len(_TIERS)} tiers defined.")
    for key, config in _TIERS.items():
        aliases = [a for a, k in TierKey.aliases().items() if k == key and a != key]
        print(f"  {key:12s} — {config.display_name:12s} {config.monthly_credits:6d} credits"
              f"   (aliases: {', '.join(sorted(set(aliases))) or 'none'})")

    print()
    print("Backward-compat checks:")
    print(f"  tier_credits('starter')      = {tier_credits('starter')}")
    print(f"  tier_credits('STARTER')      = {tier_credits('STARTER')}")  # old alias
    print(f"  tier_credits('premium')      = {tier_credits('premium')}")  # mcu_billing alias
    print(f"  tier_credits('MASTER')       = {tier_credits('MASTER')}")   # Sophia alias
    print(f"  tier_credits('TRIAL')        = {tier_credits('TRIAL')}")
    print(f"  tier_credits('starter_vn')   = {tier_credits('starter_vn')}")
    print(f"  tier_credits('growth_vn')    = {tier_credits('growth_vn')}")
    print(f"  mcu_cost('growth', 'standard') = {mcu_cost('growth', 'standard')}")
    print(f"  tier_quotas('free').commands  = {tier_quotas('free').commands}")
    print(f"  tier_quotas('starter').commands = {tier_quotas('starter').commands}")
    print(f"  trial_config('trial')          = {trial_config('trial')}")


if __name__ == "__main__":
    _demo()
