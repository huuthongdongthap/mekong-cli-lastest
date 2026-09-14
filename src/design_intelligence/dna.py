# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Parse / validate / merge / export layer for :class:`DesignDNA`.

Adapted from Hallmark (github.com/nutlope/hallmark, MIT) — DNA here is a typed
Pydantic model, not prompt text. The functions in this module are the only
boundary between raw JSON/YAML files and the validated schema, so validation
errors surface loudly instead of being swallowed downstream.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.design_intelligence.schemas import DesignDNA

try:  # PyYAML is present in this environment (used across src/core).
    import yaml as _yaml  # type: ignore[import-untyped]

    _HAS_YAML = True
except ImportError:  # pragma: no cover — environment without yaml
    _yaml = None  # type: ignore[assignment]
    _HAS_YAML = False


def parse_dna(data: dict[str, Any]) -> DesignDNA:
    """Validate a raw dict into a :class:`DesignDNA`.

    Raises ``ValueError`` (with the underlying Pydantic error message) when the
    payload is invalid — never silently coerces or drops fields.
    """
    if not isinstance(data, dict):
        msg = f"DNA payload must be a dict, got {type(data).__name__}"
        raise ValueError(msg)
    try:
        return DesignDNA.model_validate(data)
    except ValidationError as exc:
        # Pydantic's str(exc) is already human-readable; re-raise as ValueError
        # so callers see a single, catchable failure mode.
        msg = f"invalid DesignDNA payload: {exc}"
        raise ValueError(msg) from exc


def load_dna(path: Path) -> DesignDNA:
    """Read a JSON or YAML file from ``path`` and parse it as a DesignDNA.

    Format is detected by extension (.yaml/.yml -> YAML, everything else ->
    JSON). If PyYAML is unavailable, YAML files raise a clear error rather than
    being mis-parsed as JSON.
    """
    if not path.exists():
        msg = f"DNA file not found: {path}"
        raise FileNotFoundError(msg)
    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        if not _HAS_YAML:
            msg = (
                f"{path} is a YAML file but PyYAML is not installed; "
                "install PyYAML or convert to JSON"
            )
            raise RuntimeError(msg)
        parsed = _yaml.safe_load(raw)
    else:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            if _HAS_YAML:
                # Tolerate YAML-ish files saved with a .json extension.
                parsed = _yaml.safe_load(raw)
            else:
                msg = f"{path} is not valid JSON: {exc}"
                raise ValueError(msg) from exc
    if not isinstance(parsed, dict):
        msg = f"DNA file {path} must contain a JSON/YAML object, got {type(parsed).__name__}"
        raise ValueError(msg)
    return parse_dna(parsed)


def merge_dna(base: DesignDNA, override: dict[str, Any]) -> DesignDNA:
    """Shallow-merge ``override`` on top of ``base``.

    Rules:
    * ``override`` wins over ``base`` for any key it explicitly sets.
    * ``None`` / empty containers in ``override`` do NOT overwrite existing
      values on ``base`` — they are treated as "leave as-is".
    * Unknown keys raise (DesignDNA forbids extras), which keeps merges honest.
    """
    if not isinstance(override, dict):
        msg = f"override must be a dict, got {type(override).__name__}"
        raise ValueError(msg)

    merged: dict[str, Any] = base.model_dump()
    for key, value in override.items():
        if value is None:
            continue
        if isinstance(value, (list, dict, str)) and len(value) == 0:
            continue
        merged[key] = value
    return parse_dna(merged)


def export_dna(dna: DesignDNA) -> dict[str, Any]:
    """Serialize a DesignDNA into a JSON-serializable dict.

    Enums collapse to their string values, nested models to dicts. Ready for
    the Sophia contract / persistence layer downstream.
    """
    return dna.model_dump(mode="json")