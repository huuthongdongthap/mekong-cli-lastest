# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""ALGO 8 — Agent Dispatcher.

Loads agent-specific prompts and injects domain context into message chains.
Water Protocol (水): Enriches agent prompts with hub expertise.

Step 8 Phase B — memory & learning layer: inject past relevant memory
entries and surface duplicate-action warnings.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .registry.loader import load_prompts

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(__file__).parent.parent.parent / ".mekong" / "agents"
HUBS_DIR = Path(__file__).parent.parent.parent / "packages" / "agents" / "hubs"

# Default agent system prompts (used when no .md file exists).
#
# Single source of truth is ``src/core/registry/agents.yaml``. The variable
# name and shape (``dict[str, str]``) are preserved verbatim so every caller
# — including ``load_agent_prompt``'s fallback chain — is unaffected. cso and
# planner intentionally have no prompt here (they are description-only in the
# YAML); the runtime falls back to ``f"You are the {name} agent."``.
DEFAULT_PROMPTS: dict[str, str] = load_prompts()

# Agent role → hub file mapping
ROLE_HUB_MAP: dict[str, str] = {
    # Core agents
    "cto": "engineering-hub",
    "cfo": "finance-hub",
    "cmo": "marketing-hub",
    "coo": "it-hub",
    "cs": "cs-hub",
    "sales": "sales-hub",
    "editor": "creative-hub",
    "data": "finance-hub",
    # Studio agents (v6.0)
    "studio": "studio-hub",
    "vc": "vc-hub",
    "legal": "legal-hub",
    "hr": "hr-hub",
    # Extended hubs (map to closest agent)
    "executive": "executive-hub",
    "entrepreneur": "entrepreneur-hub",
    "strategist": "binh-phap-hub",
    "community": "community-hub",
    "educator": "education-hub",
    "realtor": "real-estate-hub",
    "retailer": "retail-hub",
    "wellness": "wellness-hub",
}


def _load_matching_hub(agent_role: str) -> str:
    """Load hub content for an agent role.

    Hub files provide domain expertise to enrich agent behavior.
    Truncated to 2000 chars to avoid context overflow.
    """
    hub_name = ROLE_HUB_MAP.get(agent_role)
    if not hub_name:
        return ""

    hub_path = HUBS_DIR / f"{hub_name}.md"
    if not hub_path.exists():
        logger.warning("Hub file not found: %s", hub_path)
        return ""

    try:
        content = hub_path.read_text(encoding="utf-8").strip()
        # Strip YAML frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()
        # Truncate to avoid context overflow
        return content[:2000]
    except OSError as e:
        logger.warning("Failed to read hub file %s: %s", hub_path, e)
        return ""


def load_agent_prompt(agent_role: str, include_hub: bool = True) -> str:
    """Load agent system prompt from file, enriched with hub context.

    Priority:
    1. agents/{agent_role}.md (core identity)
    2. + packages/agents/hubs/{matched-hub}.md (domain expertise)
    3. Fallback: DEFAULT_PROMPTS

    Args:
        agent_role: Role name (cto, cfo, cmo, etc.)
        include_hub: If True, enrich with hub expertise (default True)

    Returns:
        Full system prompt for the agent.
    """
    # Load core agent identity
    core_prompt = ""
    md_path = AGENTS_DIR / f"{agent_role}.md"
    if md_path.exists():
        try:
            core_prompt = md_path.read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.warning("Failed to read agent prompt %s: %s", md_path, e)

    if not core_prompt:
        core_prompt = DEFAULT_PROMPTS.get(agent_role, f"You are a helpful {agent_role} agent.")

    if not include_hub:
        return core_prompt

    # Enrich with matching hub context
    hub_prompt = _load_matching_hub(agent_role)
    if hub_prompt:
        return f"{core_prompt}\n\n---\n\n## Domain Expertise (from Hub)\n\n{hub_prompt}"

    return core_prompt


def inject_codebase_context(messages: list[dict], goal: str) -> list[dict]:
    """Inject codebase context for code-domain tasks.

    Adds project structure hint to help the LLM understand the codebase.
    """
    cwd = os.getcwd()
    context_note = (
        f"[Context: Working in project at {cwd}. "
        f"Analyze the goal and provide actionable code.]"
    )
    enriched = list(messages)
    if enriched and enriched[-1]["role"] == "user":
        enriched[-1] = {
            "role": "user",
            "content": f"{context_note}\n\n{enriched[-1]['content']}",
        }
    return enriched


def inject_metrics_context(
    messages: list[dict], tenant_id: str
) -> list[dict]:
    """Inject metrics context for analysis-domain tasks."""
    context_note = (
        f"[Context: Analyzing data for tenant '{tenant_id}'. "
        f"Provide data-driven insights.]"
    )
    enriched = list(messages)
    if enriched and enriched[-1]["role"] == "user":
        enriched[-1] = {
            "role": "user",
            "content": f"{context_note}\n\n{enriched[-1]['content']}",
        }
    return enriched


def _memory_context_for(
    goal: str, agent_role: str, limit: int = 3
) -> tuple[str, bool]:
    """Search memory for similar past agent actions and build a context string.

    Returns:
        (context_block, found) — context_block is empty string if no match.
    """
    try:
        from src.core.adapters.jsonl_memory_adapter import JsonlMemoryAdapter

        adapter = JsonlMemoryAdapter()
        hits = adapter.search(query=goal, limit=limit)
    except Exception as exc:  # pragma: no cover — defensive, memory is optional
        logger.debug("Memory search skipped: %s", exc)
        return "", False

    if not hits:
        return "", False

    lines: list[str] = [
        f"[memory: Step 8 Phase B — {len(hits)} similar past action(s) retrieved]"
    ]
    for h in hits:
        meta = h.metadata if isinstance(h.metadata, dict) else {}
        agent = meta.get("agent") or "-"
        tags = meta.get("tags") or []
        outcome = h.data.decode("utf-8", errors="replace") if h.data else "-"
        lines.append(
            f"- [{agent} / {outcome}] {h.key}"
            + (f" | tags={','.join(tags)}" if tags else "")
        )
    lines.append("[end memory]")
    return "\n".join(lines), True


def _duplicate_warning(goal: str, context: str) -> str | None:
    """Return a duplicate-action warning string if the same goal+context was seen before."""
    try:
        from src.core.memory_store import MemoryStore, DEFAULT_MEMORY_PATH

        store = MemoryStore(path=DEFAULT_MEMORY_PATH)
        prior = store.has_similar(goal=goal, context=context)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("Duplicate detection skipped: %s", exc)
        return None
    if prior is None:
        return None
    return (
        f"[duplicate warning] Similar action found in past memory: "
        f"agent={prior.agent} action={prior.action} outcome={prior.outcome} "
        f"at {prior.timestamp}. Consider reusing prior result."
    )


def build_message_chain(
    goal: str,
    agent_role: str,
    domain: str,
    tenant_id: str = "",
    agent: Any = None,
    tool_registry: Any = None,
    *,
    inject_memory: bool = True,
) -> tuple[list[dict], str, list[str]]:
    """Build complete message chain with agent prompt and context.

    Step 8 Phase B — memory & learning layer:
    - Searches .mekong/memory.jsonl for similar past actions and injects
      them into the user message when a match is found.
    - Surfaces a duplicate-action warning (assistant prefill) when the
      same goal+context has been executed before.

    Args:
        goal: User goal/request.
        agent_role: Agent role name (cto, cfo, etc.).
        domain: Task domain ('code', 'analysis', etc.).
        tenant_id: Optional tenant identifier.
        agent: Optional AgentBase instance for tool restriction.
        tool_registry: Optional ToolRegistry for filtering tools.
        inject_memory: When True (default), enrich with memory.

    Returns:
        Tuple of (messages, system_prompt, available_tools).
        - messages: chat messages list.
        - system_prompt: agent identity prompt.
        - available_tools: filtered tool names, or empty list if no restriction.
    """
    system_prompt = load_agent_prompt(agent_role)
    messages: list[dict] = [{"role": "user", "content": goal}]

    # Determine available tools for this agent
    available_tools: list[str] = []
    if agent is not None and tool_registry is not None:
        available_tools = [
            t.name for t in tool_registry.list_for_agent(agent)
        ]

    if domain == "code":
        messages = inject_codebase_context(messages, goal)
    elif domain == "analysis":
        messages = inject_metrics_context(messages, tenant_id)

    # Step 8 — inject memory context + duplicate warning
    if inject_memory:
        context_block, found = _memory_context_for(goal, agent_role)
        if found and messages and messages[-1]["role"] == "user":
            messages[-1] = {
                "role": "user",
                "content": f"{context_block}\n\n{messages[-1]['content']}",
            }
        dup_warning = _duplicate_warning(
            goal=goal,
            context=messages[-1]["content"] if messages else goal,
        )
        if dup_warning:
            messages.append({"role": "assistant", "content": dup_warning})

    return messages, system_prompt, available_tools
