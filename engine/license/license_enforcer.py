"""
License Enforcer — Runtime tier gating for commands.

Called at command entry; raises HTTPException (HTTP 402) when
current license tier is below the required tier.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from .license_store import get_license_store
from ..billing.tier_config import Tier

logger = logging.getLogger(__name__)


class LicenseEnforcer:
    """Gate commands by license tier."""

    def __init__(self) -> None:
        self._store = None

    def _get_store(self):
        if self._store is None:
            self._store = get_license_store()
        return self._store

    def get_current_tier(self, user_id: Optional[str] = None) -> Tier:
        """Return the active Tier for `user_id`, defaulting to TIER.FREE."""
        try:
            lic = self._get_store().get_active_license(user_id)
            if lic and lic.tier:
                return Tier(lic.tier)
        except Exception as exc:
            logger.debug("License lookup failed: %s", exc)
        return Tier.FREE  # fail-open

    def require_tier(self, minimum: Tier, user_id: Optional[str] = None) -> None:
        """Raise HTTP 402 if current tier < minimum."""
        current = self.get_current_tier(user_id)
        order = {
            Tier.FREE: 0,
            Tier.TRIAL: 1,
            Tier.STARTER: 2,
            Tier.GROWTH: 3,
            Tier.PRO: 4,
            Tier.ENTERPRISE: 5,
        }
        if order.get(current, 0) < order.get(minimum, 0):
            logger.warning(
                "Tier gate: required=%s current=%s user=%s", minimum, current, user_id
            )
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "tier_required",
                    "required": minimum.value,
                    "current": current.value,
                    "upgrade_url": "https://mekong.ai/pricing",
                },
            )


# ── Decorator ────────────────────────────────────────────────────────────────

_enforcer = LicenseEnforcer()


def require_tier(minimum: Tier):
    """Decorator: raise 402 if active license is below `minimum` tier.

    Usage:
        @require_tier(Tier.PRO)
        def my_command(...): ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            _enforcer.require_tier(minimum)
            return func(*args, **kwargs)
        return wrapper
    return decorator
