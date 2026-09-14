"""License store: wrapper around ~/.mekong/licenses.json.

Provides lookup, status, and tier resolution for license-gating middleware.
The Polar webhook (`src/api/polar_webhook.py`) writes records to the same file.

Schema (per license_key):
    {
      "subscription_id": "sub_xxx",
      "customer_id": "cus_xxx",
      "customer_email": "user@example.com",
      "tier": "starter|growth|pro",
      "product_name": "...",
      "created_at": "2026-04-27T...",
      "status": "active|cancelled"
    }
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _default_path() -> Path:
    override = os.environ.get("LICENSE_STORE_PATH")
    if override:
        return Path(override)
    return Path.home() / ".mekong" / "licenses.json"


class ActiveLicense:
    """Represents an active license record with attribute and key-based access."""

    def __init__(self, key: str, record: dict) -> None:
        self.license_key = key
        self.tier = record.get("tier", "free")
        self.status = record.get("status", "active")
        self.customer_id = record.get("customer_id")
        self.customer_email = record.get("customer_email")
        self.subscription_id = record.get("subscription_id")
        self.product_name = record.get("product_name")
        self.created_at = record.get("created_at")
        self._raw = record

    def __getitem__(self, item: str):
        return self._raw[item]

    def get(self, item: str, default=None):
        return self._raw.get(item, default)

    def __repr__(self) -> str:
        return f"<ActiveLicense {self.license_key} tier={self.tier} customer_id={self.customer_id}>"


class LicenseStore:
    """Read-only-ish accessor for the licenses.json store."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or _default_path()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("license_store.load_failed", extra={"error": str(exc)})
            return {}

    def get(self, license_key: str) -> Optional[dict]:
        """Return full record for a license key, or None if not found."""
        return self._load().get(license_key)

    def is_active(self, license_key: str) -> bool:
        """True only when license exists and status == 'active'."""
        record = self.get(license_key)
        return bool(record and record.get("status") == "active")

    def tenant_id(self, license_key: str) -> Optional[str]:
        """Customer ID acts as tenant ID for credit/MCU accounting."""
        record = self.get(license_key)
        return record.get("customer_id") if record else None

    def tier(self, license_key: str) -> Optional[str]:
        record = self.get(license_key)
        return record.get("tier") if record else None

    def get_active_license(self, user_id: Optional[str] = None) -> Optional[ActiveLicense]:
        """Look up an active license for a given user_id/license_key/email/subscription_id.

        Matches against:
          1. Direct match on license_key (dict key)
          2. Match on customer_id
          3. Match on customer_email
          4. Match on subscription_id

        Returns ActiveLicense only if status == 'active'. If user_id is None,
        checks MEKONG_LICENSE_KEY or MEKONG_USER_ID environment variables, or returns None.
        """
        data = self._load()
        if not data:
            return None

        lookup_id = user_id or os.environ.get("MEKONG_LICENSE_KEY") or os.environ.get("MEKONG_USER_ID")
        if not lookup_id:
            return None

        # 1. Direct match on license_key
        if lookup_id in data:
            rec = data[lookup_id]
            if rec.get("status") == "active":
                return ActiveLicense(lookup_id, rec)

        # 2. Match on customer_id, customer_email, or subscription_id
        for key, rec in data.items():
            if rec.get("status") == "active":
                if lookup_id in (
                    rec.get("customer_id"),
                    rec.get("customer_email"),
                    rec.get("subscription_id"),
                ):
                    return ActiveLicense(key, rec)

        return None


_default_store: Optional[LicenseStore] = None


def get_license_store() -> LicenseStore:
    """Module-level singleton accessor."""
    global _default_store
    if _default_store is None:
        _default_store = LicenseStore()
    return _default_store
