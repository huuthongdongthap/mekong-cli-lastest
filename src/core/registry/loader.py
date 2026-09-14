"""YAML loader for the agent declarative registry.

Parses ``agents.yaml`` into :class:`AgentDefinition` records. Fail-loud:
any structural problem (missing file, bad YAML, entry missing ``prompt``)
raises :class:`RegistryLoadError` rather than silently producing a partial
registry.

Semantic validation of ``risk_level`` / ``approval_policy`` is intentionally
NOT duplicated here — it stays in :class:`src.core.agent_registry.AgentMeta`,
which is the single authority. A bad value in the YAML therefore surfaces at
registration time, exactly as it would for a programmatically registered
agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised only when pyyaml is absent
    import yaml
except ImportError as _yaml_exc:  # pragma: no cover
    yaml = None  # type: ignore[assignment]
    _YAML_IMPORT_ERROR = _yaml_exc
else:
    _YAML_IMPORT_ERROR = None


class RegistryLoadError(Exception):
    """Raised when the agent YAML registry cannot be loaded."""


# Package-internal location of the canonical agents.yaml.
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent / "agents.yaml"


@dataclass
class AgentDefinition:
    """One declarative agent record from agents.yaml.

    At least one of ``description`` / ``prompt`` is required — an entry with
    neither carries no declarative content and is rejected at load time.
    """

    name: str
    description: str | None = None
    prompt: str | None = None
    risk_level: str = "LOW"
    approval_policy: str = "AUTO"
    extra: dict[str, Any] = field(default_factory=dict)


def _require_yaml() -> Any:
    """Return the yaml module or raise RegistryLoadError if unavailable."""
    if yaml is None:
        raise RegistryLoadError(
            "pyyaml is required for the YAML agent registry"
        ) from _YAML_IMPORT_ERROR
    return yaml


def _parse_raw(raw: dict[str, Any], source: str) -> dict[str, AgentDefinition]:
    """Validate raw mapping shape and coerce to AgentDefinition records."""
    if not isinstance(raw, dict):
        raise RegistryLoadError(
            f"{source}: top-level YAML must be a mapping of agent names"
        )

    definitions: dict[str, AgentDefinition] = {}
    for name, entry in raw.items():
        if not isinstance(name, str) or not name:
            raise RegistryLoadError(f"{source}: agent name must be a non-empty string")
        if not isinstance(entry, dict):
            raise RegistryLoadError(
                f"{source}: agent '{name}' must be a mapping of fields, got {type(entry).__name__}"
            )
        prompt = entry.get("prompt")
        if prompt is not None and (not isinstance(prompt, str) or not prompt.strip()):
            raise RegistryLoadError(
                f"{source}: agent '{name}': 'prompt' must be a non-empty string"
            )
        description = entry.get("description")
        if description is not None and (not isinstance(description, str) or not description.strip()):
            raise RegistryLoadError(
                f"{source}: agent '{name}': 'description' must be a non-empty string"
            )
        if prompt is None and description is None:
            raise RegistryLoadError(
                f"{source}: agent '{name}' needs at least one of "
                "'description' or 'prompt'"
            )
        risk_level = entry.get("risk_level", "LOW")
        approval_policy = entry.get("approval_policy", "AUTO")
        if not isinstance(risk_level, str) or not isinstance(approval_policy, str):
            raise RegistryLoadError(
                f"{source}: agent '{name}': risk_level/approval_policy must be strings"
            )
        extra = {
            k: v
            for k, v in entry.items()
            if k not in {"description", "prompt", "risk_level", "approval_policy"}
        }
        definitions[name] = AgentDefinition(
            name=name,
            prompt=prompt,
            description=description,
            risk_level=risk_level,
            approval_policy=approval_policy,
            extra=extra,
        )
    return definitions


def load_agents_yaml(
    path: str | Path | None = None,
) -> dict[str, AgentDefinition]:
    """Load agent definitions from ``agents.yaml``.

    Args:
        path: Filesystem path to a YAML registry. ``None`` loads the
            package-internal ``agents.yaml`` next to this module.

    Returns:
        Mapping of agent name → :class:`AgentDefinition`.

    Raises:
        RegistryLoadError: If the file is missing, YAML is malformed, or an
            entry fails structural validation.
    """
    yaml_mod = _require_yaml()
    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    if not registry_path.exists():
        raise RegistryLoadError(
            f"agent registry file not found: {registry_path}"
        )
    try:
        with registry_path.open("r", encoding="utf-8") as handle:
            raw = yaml_mod.safe_load(handle)
    except yaml_mod.YAMLError as exc:
        raise RegistryLoadError(
            f"invalid YAML in agent registry {registry_path}: {exc}"
        ) from exc
    except OSError as exc:
        raise RegistryLoadError(
            f"cannot read agent registry {registry_path}: {exc}"
        ) from exc
    return _parse_raw(raw, str(registry_path))


def load_descriptions(
    path: str | Path | None = None,
) -> dict[str, str]:
    """Return ``{name: description}`` for every entry that defines one."""
    return {
        name: definition.description
        for name, definition in load_agents_yaml(path).items()
        if definition.description is not None
    }


def load_prompts(path: str | Path | None = None) -> dict[str, str]:
    """Return ``{name: prompt}`` for every entry that defines one."""
    return {
        name: definition.prompt
        for name, definition in load_agents_yaml(path).items()
        if definition.prompt is not None
    }


__all__ = [
    "AgentDefinition",
    "RegistryLoadError",
    "load_agents_yaml",
    "load_descriptions",
    "load_prompts",
    "DEFAULT_REGISTRY_PATH",
]