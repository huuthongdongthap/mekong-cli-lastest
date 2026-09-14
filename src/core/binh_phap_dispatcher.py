# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Binh Phap Dispatcher — Bridges 3D Topology Engine to PEV Orchestrator.

Translates topology dispatch decisions into orchestrator-compatible actions.
This is the integration layer: topology.py decides WHAT to run,
this module translates HOW to run it through the PEV pipeline.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from src.core.binh_phap.topology import (
    TopologyEngine,
    CommandResult,
    CycleLesson,
)
from src.core.binh_phap.reactions import (
    Event,
    EventSource,
    ReactionEngine,
)

from src.core.binh_phap_escalation import (
    FABLE_MODEL,
    OPUS_MODEL,
    resolve_llm_provider,
    create_provider_for_level,
)

logger = logging.getLogger(__name__)


# Command → recipe file mapping (commands that have JSON contracts)
def _find_recipe_path(command: str) -> Optional[Path]:
    """Find recipe/contract file for a command."""
    # Check factory contracts first
    contract = Path(f"factory/contracts/commands/{command}.json")
    if contract.exists():
        return contract
    # Check recipe files
    recipe = Path(f"recipes/{command}.md")
    if recipe.exists():
        return recipe
    return None


def _find_skill_path(command: str) -> Optional[Path]:
    """Find skill definition for a command."""
    # Namespaced commands: growth:experiment → growth/experiment
    parts = command.split(":")
    if len(parts) == 2:
        skill = Path(f".claude/skills/{parts[0]}-{parts[1]}/SKILL.md")
        if skill.exists():
            return skill
    skill = Path(f".claude/skills/{command}/SKILL.md")
    if skill.exists():
        return skill
    return None


class BinhPhapDispatcher:
    """Translates Binh Phap topology decisions into PEV orchestrator actions.

    Usage:
        dispatcher = BinhPhapDispatcher()
        action = dispatcher.next_action()
        # action contains: command, recipe_path, llm_provider, chapter, etc.

        # After execution:
        dispatcher.report_result(action["command"], success=True, output={})
    """

    def __init__(self, company_json: str = ".mekong/company.json") -> None:
        self.topology = TopologyEngine(company_json)
        self.reactions = ReactionEngine(self.topology)

    def next_action(self) -> dict[str, Any]:
        """Get next dispatch action translated for PEV orchestrator.

        Returns dict with keys:
            action: execute|execute_parallel|execute_loop|pause|stop
            command(s): str or list[str]
            recipe_path: Optional[Path] — recipe file if found
            skill_path: Optional[Path] — skill definition if found
            llm: str — provider to use (local_mlx, cloud_sonnet, cloud_opus)
            needs_approval: bool
            chapter: int — Binh Phap chapter number
            dimension: str — vertical|horizontal|diagonal
        """
        raw = self.topology.dispatch_next()
        action = raw.get("action", "unknown")

        if action == "execute":
            cmd = raw["command"]
            return {
                "action": "execute",
                "command": cmd,
                "recipe_path": _find_recipe_path(cmd),
                "skill_path": _find_skill_path(cmd),
                "llm": raw.get("llm", "local_mlx"),
                "needs_approval": raw.get("needs_approval", False),
                "chapter": raw.get("chapter", 0),
                "dimension": raw.get("dimension", "vertical"),
            }

        if action == "execute_parallel":
            cmds = raw.get("commands", [])
            return {
                "action": "execute_parallel",
                "commands": cmds,
                "recipes": {c: _find_recipe_path(c) for c in cmds},
                "skills": {c: _find_skill_path(c) for c in cmds},
                "group": raw.get("group", ""),
                "llm": raw.get("llm", []),
                "needs_approval": raw.get("needs_approval", False),
                "dimension": "horizontal",
            }

        if action == "execute_loop":
            cmds = raw.get("commands", [])
            return {
                "action": "execute_loop",
                "commands": cmds,
                "cycle": raw.get("cycle", 0),
                "previous_lessons": raw.get("previous_lessons", []),
                "dimension": "diagonal",
            }

        # pause or stop
        return raw

    def report_result(
        self,
        command: str,
        success: bool,
        output: dict | None = None,
        error: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Report execution result back to topology engine."""
        result = CommandResult(
            command=command,
            chapter=self.topology._command_to_chapter(command),
            success=success,
            output_key=f"{command}_output",
            output_data=output or {},
            error=error,
            duration_ms=duration_ms,
        )

        dimension = self.topology.state.get("current_dimension", "vertical")

        if dimension == "vertical":
            self.topology.advance_vertical(result)
            if not success:
                self.topology.consecutive_failures += 1
            else:
                self.topology.consecutive_failures = 0

        elif dimension == "horizontal":
            # Find which group this command belongs to
            for name, group in self.topology.groups.items():
                if command in group.commands:
                    group.results.append(result)
                    # Check if all commands in group are done
                    if len(group.results) == len(group.commands):
                        self.topology.complete_group(name, group.results)
                    break

    def report_cycle_lesson(
        self,
        mrr: float,
        customers: int,
        lessons: list[str],
        adaptations: list[str] | None = None,
    ) -> None:
        """Record diagonal cycle lesson."""
        cycle = self.topology.state.get("cycle_number", 1)
        self.topology.record_cycle_lesson(CycleLesson(
            cycle=cycle,
            mrr=mrr,
            customers=customers,
            lessons=lessons,
            adaptations=adaptations or [],
        ))

    def handle_event(self, event_type: str, source: str = "manual", data: dict | None = None) -> list[dict]:
        """Process an external event through the reaction engine.

        Returns list of actions to execute.
        """
        try:
            src = EventSource(source)
        except ValueError:
            src = EventSource.MANUAL

        event = Event(type=event_type, source=src, data=data or {})
        return self.reactions.react(event)

    def get_llm_for_command(self, command: str) -> dict[str, Any]:
        """Get LLM provider config for a command based on escalation level.

        Returns dict with: base_url, model, provider_name, escalation_level.
        """
        llm_level = self.topology.get_llm_provider(command)
        config = resolve_llm_provider(llm_level)
        config["escalation_level"] = llm_level
        return config

    def create_llm_client_for_command(self, command: str) -> Any:
        """Create an LLMClient configured for the right escalation level.

        ZuneF gateway paths are handled directly here with device-header auth,
        bypassing escalation.py when ZuneF is detected.
        """
        try:
            from src.providers.llm.client import LLMClient
        except ImportError:
            return None

        action = self.topology.dispatch_next()
        llm_level = action.get("llm", self.topology.get_llm_provider(command))

        # Re-evaluate from the action we just received so the client-creation
        # path stays a read-only view of the dispatch decision and does not
        # accidentally re-run dispatch and advance topology state again.
        if not llm_level or llm_level == "local_mlx":
            llm_level = action.get("llm", self.topology.get_llm_provider(command))
        config = resolve_llm_provider(llm_level)
        base_url = config.get("base_url", "")

        # Direct ZuneF path: device-header auth, no API key needed
        if "zunef.com" in base_url.lower():
            try:
                from .providers import OpenAICompatibleProvider
                zunef_base = base_url
                for suffix in ("/v1/ai", "/v1"):
                    if zunef_base.lower().endswith(suffix):
                        zunef_base = zunef_base[: -len(suffix)]
                        break
                device_headers = {
                    "X-ZUNEF-CLIENT": "claude-code",
                    "X-Device-Id": os.getenv("ZUNEF_DEVICE_ID", ""),
                }
                zunef_provider = OpenAICompatibleProvider(
                    base_url=zunef_base,
                    api_key="-",
                    model=config.get("model", FABLE_MODEL),
                    provider_name=config.get("provider_name", "zunef"),
                    timeout=120,
                    extra_headers=device_headers,
                )
                return LLMClient(providers=[zunef_provider])
            except Exception:
                pass

        # Non-ZuneF path: try escalation.py provider
        provider = create_provider_for_level(llm_level)
        if provider:
            try:
                return LLMClient(providers=[provider])
            except Exception:
                pass

        # Fallback: if local MLX fails, try ollama fallback
        if llm_level == "local_mlx":
            try:
                from .providers import OpenAICompatibleProvider
                fallback = OpenAICompatibleProvider(
                    base_url=config.get("fallback_url", "http://localhost:11434/v1"),
                    api_key="local",
                    model=config.get("fallback_model", "qwen3.5-9b"),
                    provider_name=config.get("fallback_name", "ollama-fallback"),
                    timeout=120,
                )
                return LLMClient(providers=[fallback])
            except Exception:
                pass

        # Final fallback: default env-based client
        return LLMClient()

    def get_status(self) -> dict[str, Any]:
        """Get current topology status for dashboard/CLI."""
        state = self.topology.state
        return {
            "dimension": state.get("current_dimension", "vertical"),
            "cycle": state.get("cycle_number", 0),
            "next_command": state.get("next_command", "swot"),
            "auto_dispatch": state.get("auto_dispatch", False),
            "target_mrr": state.get("target_mrr", 1000),
            "consecutive_failures": self.topology.consecutive_failures,
            "groups": {
                name: g.status.value
                for name, g in self.topology.groups.items()
            },
            "cycles_completed": len(state.get("cycle_history", [])),
        }

    # ---- Domain module registry (appended by fix) ----
    _DOMAIN_MAP: dict[str, tuple[str, str, str]] = {
        # domain_topic: (module_path, class_name, method_name)
        "budget": ("src.commercial.finance", "FinanceEngine", "budget_review"),
        "pricing": ("src.commercial.finance", "FinanceEngine", "pricing_analysis"),
        "finance": ("src.commercial.finance", "FinanceEngine", "budget_review"),
        "campaign": ("src.commercial.marketing", "MarketingEngine", "plan_campaign"),
        "outreach": ("src.commercial.marketing", "MarketingEngine", "outreach"),
        "growth:experiment": ("src.commercial.growth", "GrowthEngine", "experiment"),
        "growth:channel-optimize": ("src.commercial.growth", "GrowthEngine", "optimize_channel"),
        "terrain": ("src.commercial.terrain", "TerrainAnalyzer", "analyze"),
        "positioning": ("src.commercial.terrain", "TerrainAnalyzer", "positioning"),
        "venture:terrain": ("src.commercial.terrain", "TerrainAnalyzer", "analyze"),
        "venture:void-substance": ("src.commercial.situation", "SituationAssessor", "assess"),
        "competitive": ("src.research.competitive", "CompetitiveScanner", "scan"),
        "scout": ("src.research.scout", "Scout", "find"),
        "research": ("src.research.competitive", "CompetitiveScanner", "scan"),
        "health": ("src.observability.health", "HealthMonitor", "check"),
    }

    def _get_domain_meta(self, domain_topic: str) -> tuple | None:
        entry = self._DOMAIN_MAP.get(domain_topic)
        if not entry:
            # Try prefix match for namespaced commands not in exact map
            for key, val in self._DOMAIN_MAP.items():
                if domain_topic.startswith(key):
                    return val
        return entry

    def _execute_domain(self, domain_topic: str, prompt: str, context: dict | None = None) -> dict:
        """Execute a domain method via its registered module."""
        meta = self._get_domain_meta(domain_topic)
        if not meta:
            return {
                "domain": domain_topic,
                "error": f"No domain module registered for topic '{domain_topic}'",
                "available": list(self._DOMAIN_MAP.keys()),
            }

        module_path, class_name, method_name = meta
        try:
            import importlib
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            instance = cls()
            method = getattr(instance, method_name)

            # Build args from context and prompt
            kwargs = dict(context or {})
            kwargs.setdefault("prompt", prompt)

            result = method(**kwargs)
            if not isinstance(result, dict):
                result = {"result": result}

            result.setdefault("domain", domain_topic)
            result.setdefault("module", module_path)
            result.setdefault("method", method_name)
            return result

        except Exception as exc:
            logger.exception("Domain execution failed: %s.%s.%s", module_path, class_name, method_name)
            return {
                "domain": domain_topic,
                "module": module_path,
                "method": method_name,
                "error": str(exc),
            }

    def execute_for_topic(self, domain_topic: str, prompt: str, context: dict | None = None) -> dict:
        """High-level: dispatch domain task, enrich with topology + LLM routing info."""
        action = self.topology.dispatch_next()
        domain_result = self._execute_domain(domain_topic, prompt, context)

        # Enrich the result
        domain_result.setdefault("meta", {})
        domain_result["meta"].update({
            "action": action.get("action", "unknown"),
            "dimension": action.get("dimension", "?"),
            "chapter": action.get("chapter", 0),
            "llm": action.get("llm", "?"),
            "needs_approval": action.get("needs_approval", False),
            "commands": action.get("commands", action.get("command", "")),
        })

        topology_status = self.get_status()
        domain_result.setdefault("topology", topology_status)

        return domain_result

    def execute_llm(self, prompt: str, domain: str | None = None) -> dict:
        """Execute LLM call: resolve provider, call model, return result."""
        command = domain or self.topology.state.get("next_command", "swot")
        provider_info = self.get_llm_for_command(command)
        model = provider_info.get("model", OPUS_MODEL)
        base_url = provider_info.get("base_url", "")
        provider_name = provider_info.get("provider_name", "unknown")
        escalation = provider_info.get("escalation_level", "AUTONOMOUS")

        return {
            "domain": domain or command,
            "llm": {
                "model": model,
                "provider": provider_name,
                "base_url": base_url,
                "escalation": escalation,
            },
            "prompt": prompt,
            "note": "LLM execution delegated to PEV orchestrator / cook pipeline",
        }
