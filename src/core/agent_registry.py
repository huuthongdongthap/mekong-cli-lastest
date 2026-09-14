# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Mekong CLI - Agent Registry.

Type-safe registry for AgentBase subclasses.
Replaces the plain AGENT_REGISTRY dict with validation at registration time.
Extended with tool restriction validation and markdown agent discovery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent_base import AgentBase
from .registry.loader import load_descriptions

logger = logging.getLogger(__name__)


@dataclass
class AgentMeta:
    """Rich metadata surfaced by ``mekong agent list``."""

    name: str
    description: str
    cls: type[AgentBase]
    allowed_tools: list[str] = field(default_factory=list)
    spawnable_agents: list[str] = field(default_factory=list)
    # E3 — Declarative policy fields (backward-compatible defaults)
    risk_level: str = "LOW"
    max_budget: float | None = None
    max_iterations: int | None = None
    approval_policy: str = "AUTO"  # AUTO | MANUAL | DENY
    model_preference: str | None = None

    def __post_init__(self) -> None:
        """Validate policy fields."""
        valid_risk = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        if self.risk_level not in valid_risk:
            raise ValueError(f"Invalid risk_level: {self.risk_level}. Must be one of {valid_risk}")
        valid_approval = {"AUTO", "MANUAL", "DENY"}
        if self.approval_policy not in valid_approval:
            raise ValueError(f"Invalid approval_policy: {self.approval_policy}. Must be one of {valid_approval}")
        if self.risk_level == "CRITICAL" and self.approval_policy == "AUTO":
            raise ValueError("CRITICAL risk agents cannot have approval_policy=AUTO")


class AgentRegistry:
    """Type-safe registry for Mekong agents.

    Validates that only AgentBase subclasses are registered and provides
    informative KeyError messages when an unknown agent is requested.

    Example::

        registry = AgentRegistry()
        registry.register("git", GitAgent)
        agent_cls = registry.get("git")
        agent = agent_cls()

    Extended: validates allowedTools against known tool names at registration,
    auto-discovers ``.claude/agents/*.md`` files, and exposes a rich
    ``discover()`` interface for the CLI ``mekong agent list`` command.
    """

    def __init__(self) -> None:
        self._agents: dict[str, type[AgentBase]] = {}
        self._meta: dict[str, AgentMeta] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        cls: type,
        *,
        description: str = "",
        allowed_tools: list[str] | None = None,
        spawnable_agents: list[str] | None = None,
        # E3 — Declarative policy fields
        risk_level: str = "LOW",
        max_budget: float | None = None,
        max_iterations: int | None = None,
        approval_policy: str = "AUTO",
        model_preference: str | None = None,
    ) -> None:
        """Register an agent class under a short name.

        Args:
            name: Short lookup key (e.g. "git", "file").
            cls: Class to register — should subclass ``AgentBase`` (warns for
                non-compliant classes for plugin compatibility).
            description: Human-readable description surfaced by
                ``mekong agent list``. Falls back to the class docstring and
                then the name itself when omitted.
            allowed_tools: Optional tool allowlist for this agent.
            spawnable_agents: Optional list of delegatable agent IDs.
            risk_level: Risk classification (LOW, MEDIUM, HIGH, CRITICAL). Default LOW.
            max_budget: Optional max budget (MCU/USD) for this agent. Default None.
            max_iterations: Optional max iterations for this agent. Default None.
            approval_policy: Approval policy (AUTO, MANUAL, DENY). Default AUTO.
            model_preference: Optional preferred model ID. Default None.
        """
        if not isinstance(cls, type) or not issubclass(cls, AgentBase):
            # Softened: warn instead of hard error for plugin compatibility.
            logger.warning(
                "%r is not an AgentBase subclass — registering under '%s' "
                "but it may not work with the PEV loop.",
                cls,
                name,
            )
            # Still allow registration for plugin compatibility.

        # Validate allowed_tools against known tool names.
        if allowed_tools:
            from .tool_names import resolve_tool_name, ALL_TOOL_NAMES

            unknown = [
                tool
                for tool in allowed_tools
                if resolve_tool_name(tool) not in ALL_TOOL_NAMES and tool != "*"
            ]
            if unknown:
                logger.warning(
                    "Unknown tool(s) in allowed_tools for '%s': %s. "
                    "Known tools: %s",
                    name,
                    unknown,
                    sorted(ALL_TOOL_NAMES),
                )

        self._agents[name] = cls
        self._meta[name] = AgentMeta(
            name=name,
            description=description or cls.__doc__ or name,
            cls=cls,
            allowed_tools=list(allowed_tools or []),
            spawnable_agents=list(spawnable_agents or []),
            risk_level=risk_level,
            max_budget=max_budget,
            max_iterations=max_iterations,
            approval_policy=approval_policy,
            model_preference=model_preference,
        )

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> type[AgentBase]:
        """Retrieve a registered agent class by name.

        Args:
            name: Registered agent name.

        Returns:
            Agent class (not instance).

        Raises:
            KeyError: With available agent list when *name* is not registered.
        """
        if name not in self._agents:
            available = list(self._agents.keys())
            msg = f"Unknown agent: '{name}'. Available agents: {available}"
            raise KeyError(msg)
        return self._agents[name]

    def get_meta(self, name: str) -> dict[str, Any]:
        """Get metadata for a registered agent (allowed_tools, spawnable_agents)."""
        meta = self._meta.get(name)
        if meta is None:
            return {"allowed_tools": [], "spawnable_agents": []}
        return {
            "allowed_tools": list(meta.allowed_tools),
            "spawnable_agents": list(meta.spawnable_agents),
        }

    def get_meta_obj(self, name: str) -> AgentMeta | None:
        """Return the rich :class:`AgentMeta` dataclass for *name*, or ``None``."""
        return self._meta.get(name)

    # ------------------------------------------------------------------
    # Discovery / enumeration (matches what ``agent_commands`` expects)
    # ------------------------------------------------------------------

    def list_agents(self) -> list[str]:
        """Return sorted list of registered agent names."""
        return sorted(self._agents.keys())

    def list(self) -> list[str]:
        """Compatibility alias for :meth:`list_agents`."""
        return self.list_agents()

    def discover(self) -> list[AgentMeta]:
        """Return rich metadata for every registered agent.

        Used by ``mekong agent list`` to render the agent table.
        """
        return [self._meta[name] for name in self.list_agents()]

    def register_decorator(self, name: str) -> Any:
        """Decorator factory — register a class when it is defined.

        Example::

            @registry.register_decorator("git")
            class GitAgent(AgentBase):
                ...
        """

        def wrapper(cls: type) -> type:
            self.register(name, cls)
            return cls

        return wrapper

    def __contains__(self, name: object) -> bool:
        """Support ``'git' in registry`` syntax."""
        return name in self._agents

    def __len__(self) -> int:
        return len(self._agents)

    def __repr__(self) -> str:
        return f"<AgentRegistry agents={self.list_agents()}>"


# ---------------------------------------------------------------------------
# Module-level singleton — auto-discovered on first access.
# ---------------------------------------------------------------------------

_SINGLETON: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    """Return the process-wide :class:`AgentRegistry`, discovering markdown
    agents the first time it is called."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = AgentRegistry()
        _register_known_agents(_SINGLETON)
        _discover_markdown_agents(_SINGLETON)
    return _SINGLETON


def _register_known_agents(registry: AgentRegistry) -> None:
    """Register the built-in C-suite + planner agents as stubs.

    Markdown discovery only fires when ``.claude/agents/*.md`` exists. The
    canonical agents (cto, cmo, coo, cfo, cso, planner) must be discoverable
    regardless of filesystem state, so they are registered here first.

    The ``cli`` agent is the default runtime agent for unmatched intents
    (e.g. ``"echo hello"``). It is registered FIRST so the registry's
    ``_RegistryDispatcher`` can resolve it — without it every goal routed to
    the runtime's ``self._agent_id`` (``"cli"``) fails with
    ``NotImplementedError`` and never executes (Lane E8 regression).
    """
    if "cli" not in registry._agents:
        try:
            registry.register(
                "cli",
                _CliShellAgent,
                description="Default CLI runtime agent — runs local shell goals through CommandSanitizer",
                allowed_tools=["shell:run"],
                spawnable_agents=[],
                risk_level="MEDIUM",
                approval_policy="AUTO",
            )
        except Exception as exc:  # pragma: no cover - discovery guard
            logger.debug("Failed to register 'cli' agent: %s", exc)

    for name, description in _DEFAULT_DESCRIPTIONS.items():
        if name in registry._agents:
            continue
        try:
            registry.register(
                name,
                _make_markdown_agent_class(name, f"You are the {name} agent."),
                description=description,
                allowed_tools=[],
                spawnable_agents=[],
            )
        except Exception as exc:  # pragma: no cover - discovery guard
            logger.debug("Failed to register known agent %r: %s", name, exc)


# ---------------------------------------------------------------------------
# .claude/agents/*.md auto-discovery
# ---------------------------------------------------------------------------

AGENTS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "agents"

# ---------------------------------------------------------------------------
# C-suite descriptions — single source of truth is agents.yaml
# ---------------------------------------------------------------------------
# Historically these were inline Python literals here. They now derive from
# ``src/core/registry/agents.yaml`` so the YAML is the single source of truth
# and there is no duplicate copy to drift. The variable name and shape
# (``dict[str, str]``) are preserved verbatim so every caller is unaffected.
# A YAML load failure (missing file, malformed YAML, invalid entry) raises
# RegistryLoadError at import time — fail-loud by design.
_DEFAULT_DESCRIPTIONS: dict[str, str] = load_descriptions()

_AGENT_ROLE_HINTS: dict[str, str] = {
    "cto": "code",
    "cmo": "marketing",
    "coo": "operations",
    "cfo": "finance",
    "cso": "analysis",
    "planner": "plan",
}


def _description_from_frontmatter(text: str, fallback: str) -> str:
    """Return the value of the ``description:`` YAML field or *fallback*."""
    if not text.startswith("---"):
        return fallback
    try:
        _, body, _ = text.split("---", 2)
    except ValueError:
        return fallback
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("description:"):
            value = line[len("description:") :].strip()
            if value and value[0] in "\"'":
                return value.strip("\"'")
            return value
    return fallback


class _CliShellAgent(AgentBase):
    """Default runtime agent for goals that map to a local shell command.

    Lane E8: the canonical runtime's ``execute()`` dispatches through the
    registry (``_RegistryDispatcher``) and calls ``agent_instance.run()``.
    Previously every unmatched intent (e.g. ``"echo hello"``) resolved to the
    unregistered ``"cli"`` agent and failed with ``NotImplementedError`` — the
    graceful failure path, but never an actual execution.

    This agent closes the loop: it treats the goal text as a shell command,
    runs it through ``CommandSanitizer`` (fail-closed, same gate as the
    ``shell:run`` capability) and returns the captured output. It is the
    single canonical bridge between ``mekong cook`` and the local runtime,
    so the Binh Phap ``RecipeOrchestrator`` engine can stay as a legacy
    consumer (escrow) while the CLI moves to the runtime path.
    """

    def __init__(self, name: str = "cli", **kwargs: object) -> None:
        super().__init__(name=name)

    def plan(self, input_data: str) -> list[Any]:  # noqa: ANN001
        from .agent_base import Task, TaskStatus  # local import avoids circular

        return [
            Task(
                id=f"{self.name}-1",
                description=input_data,
                input={"command": input_data},
                status=TaskStatus.PENDING,
            )
        ]

    def execute(self, task: Any) -> Any:  # noqa: ANN001
        from .agent_base import Result, TaskStatus  # local import avoids circular

        command = str(task.input.get("command") or task.description or "")
        task.status = TaskStatus.RUNNING
        try:
            from .command_sanitizer import CommandSanitizer

            san = CommandSanitizer(strict_mode=True).sanitize(command)
            if not san.is_safe:
                blocked = "; ".join(san.blocked_patterns) or san.blocked_reason or "unknown"
                return Result(
                    task_id=task.id,
                    success=False,
                    error=f"shell:run blocked by CommandSanitizer: {blocked}",
                )
            command = san.sanitized_command or command
        except ImportError:
            return Result(
                task_id=task.id,
                success=False,
                error="CommandSanitizer module missing — shell:run blocked (fail-closed)",
            )

        import shlex
        import subprocess

        try:
            proc = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = proc.stdout or proc.stderr
            if proc.returncode != 0:
                task.status = TaskStatus.FAILED
                return Result(
                    task_id=task.id,
                    success=False,
                    output=output.strip(),
                    error=f"Exit code {proc.returncode}: {output}",
                )
            task.status = TaskStatus.SUCCESS
            return Result(task_id=task.id, success=True, output=output.strip())
        except Exception as exc:  # noqa: BLE001 - surface as terminal error
            task.status = TaskStatus.FAILED
            return Result(task_id=task.id, success=False, error=str(exc))


def _make_markdown_agent_class(role: str, prompt: str) -> type[AgentBase]:
    """Build a minimal AgentBase subclass for a markdown-discovered agent."""

    def plan(self: Any, input_data: str) -> list[Any]:  # noqa: ANN001
        from .agent_base import Task  # local import avoids circular

        return [
            Task(
                id=f"{role}-1",
                description=f"Run {role} agent",
                input={"text": input_data},
            )
        ]

    def execute(self: Any, task: Any) -> Any:  # noqa: ANN001
        from .agent_base import Result, TaskStatus  # local import avoids circular

        task.status = TaskStatus.SUCCESS
        truncated = prompt[:240] + ("..." if len(prompt) > 240 else "")
        return Result(
            task_id=task.id,
            success=True,
            output=f"[{role.upper()}] {truncated}",
        )

    return type(
        f"Markdown{role.capitalize()}Agent",
        (AgentBase,),
        {"__doc__": _DEFAULT_DESCRIPTIONS.get(role, role), "plan": plan, "execute": execute},
    )


def _discover_markdown_agents(registry: AgentRegistry) -> None:
    """Walk ``.claude/agents`` and register any ``*.md`` files as agents."""
    if not AGENTS_DIR.is_dir():
        logger.debug("Agents directory not found at %s — skipping markdown discovery.", AGENTS_DIR)
        return

    from .agent_dispatcher import DEFAULT_PROMPTS, load_agent_prompt

    for md_path in sorted(AGENTS_DIR.glob("*.md")):
        name = md_path.stem
        try:
            content = md_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.debug("Skipping %r: %s", md_path, exc)
            continue

        description = _description_from_frontmatter(
            content,
            _DEFAULT_DESCRIPTIONS.get(name, f"{name} agent"),
        )
        prompt = DEFAULT_PROMPTS.get(name)
        if prompt is None:
            try:
                prompt = load_agent_prompt(name, include_hub=False)
            except Exception as exc:  # pragma: no cover - discovery guard
                logger.debug("Could not load prompt for %r: %s", name, exc)
                prompt = f"You are the {name} agent."

        try:
            agent_cls = _make_markdown_agent_class(name, prompt)
        except Exception as exc:  # pragma: no cover - discovery guard
            logger.debug("Skipping agent class build for %r: %s", name, exc)
            continue

        try:
            registry.register(
                name,
                agent_cls,
                description=description,
                allowed_tools=[],
                spawnable_agents=[],
            )
            logger.debug("Discovered agent %r from %s", name, md_path)
        except Exception as exc:  # pragma: no cover - discovery guard
            logger.debug("Failed to register agent %r: %s", name, exc)


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "AgentRegistry",
    "AgentMeta",
    "get_registry",
    "AGENTS_DIR",
]
