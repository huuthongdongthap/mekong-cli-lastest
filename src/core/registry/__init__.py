"""Declarative agent registry package.

Single source of truth for agent declarative definitions lives in
``agents.yaml``; :mod:`src.core.registry.loader` parses it into
:class:`~src.core.registry.loader.AgentDefinition` records. The runtime
registries (``agent_registry`` / ``agent_dispatcher``) derive their module
level defaults from this YAML so there are no duplicate agent definitions
across YAML / Python / CLI / prompts.

Backward-compat: the legacy module-level functions ``load_agents_dynamic``
and ``get_agent`` (previously in ``src.core.registry`` module) are re-exported
here so existing importers keep resolving — the canonical dynamic-discovery
implementation lives in ``src.core.registry.dynamic``; this is a thin alias,
not a second implementation.
"""

from __future__ import annotations

from src.core.registry.dynamic import get_agent, load_agents_dynamic
from src.core.registry.loader import (
    AgentDefinition,
    RegistryLoadError,
    load_agents_yaml,
)

__all__ = [
    "AgentDefinition",
    "RegistryLoadError",
    "load_agents_yaml",
    "load_agents_dynamic",
    "get_agent",
]
