# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Dynamic agent discovery from ``src/agents/`` and ``plugins/``.

Split out of the legacy ``src/core/registry.py`` module so the package
``src/core/registry/`` can re-export ``load_agents_dynamic`` and ``get_agent``
without keeping the recipe-registry classes in the same namespace. This is
the canonical implementation — ``src/core/registry/__init__.py`` is a thin
re-export, not a second copy.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Dict, Optional, Type

from src.core.agent_base import AgentBase


def _scan_directory_for_agents(
    directory: Path, module_prefix: str
) -> Dict[str, Type[AgentBase]]:
    """Scan a directory for AgentBase subclasses.

    Args:
        directory: Path to scan for agent modules
        module_prefix: Python module prefix (e.g. 'src.agents')

    Returns:
        Dict mapping lowercase agent name to class
    """
    agents: Dict[str, Type[AgentBase]] = {}
    if not directory.exists():
        return agents

    for py_file in directory.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        module_name = f"{module_prefix}.{py_file.stem}"
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, AgentBase) and obj is not AgentBase:
                # Derive short name: prefer the class' own `.name`, else strip
                # the "Agent" suffix from the class name (GitAgent -> "git").
                # `obj` is the class (type[AgentBase]); `.name` is a class
                # attribute only some subclasses declare, so read it via
                # getattr rather than a direct attribute access.
                declared = getattr(obj, "name", None)
                if isinstance(declared, str) and declared.strip():
                    agents[declared.lower()] = obj
                else:
                    cls_name = obj.__name__
                    short = cls_name.replace("Agent", "").lower()
                    agents[short] = obj
    return agents


def load_agents_dynamic() -> Dict[str, Type[AgentBase]]:
    """Dynamically discover agent classes from src/agents/ and plugins/.

    Returns:
        Dict mapping lowercase agent name to class
    """
    agents: Dict[str, Type[AgentBase]] = {}

    # registry/dynamic.py → src/core/registry → src/core → src/agents
    builtin_dir = Path(__file__).resolve().parent.parent.parent / "agents"
    agents.update(_scan_directory_for_agents(builtin_dir, "src.agents"))

    plugins_dir = Path("plugins")
    if plugins_dir.exists():
        plugins_abs = str(plugins_dir.resolve().parent)
        if plugins_abs not in sys.path:
            sys.path.insert(0, plugins_abs)
        agents.update(_scan_directory_for_agents(plugins_dir, "plugins"))

    return agents


def get_agent(name: str) -> Optional[Type[AgentBase]]:
    """Look up an agent class by short name.

    Args:
        name: Agent short name (e.g. 'git', 'file', 'shell')

    Returns:
        Agent class or None if not found
    """
    registry = load_agents_dynamic()
    return registry.get(name.lower())


__all__ = ["load_agents_dynamic", "get_agent"]