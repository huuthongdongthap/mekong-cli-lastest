# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""MekongCoreRuntime Protocol — Buzz Adapter. Provider-agnostic: goal->plan->delegate->execute->observe->verify->repair->remember->commit. No Buzz/MCP hardcoding."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

from src.core.protocols import Plan, PlanStatus, Step, GoalEngine
from src.core.memory_separation import MemoryTier
from src.core.dag_scheduler import DAGScheduler, _get_order

logger = logging.getLogger(__name__)


class RepairStrategy(str, Enum):
    RETRY, FALLBACK, ESCALATE, ROLLBACK = "retry", "fallback", "escalate", "rollback"

class Scope(str, Enum):
    SESSION, ORG, GLOBAL = "session", "org", "global"

@dataclass(frozen=True)
class AgentId:
    name: str

@dataclass(frozen=True)
class CheckSpec:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class SideEffect:
    kind: str
    target: str
    data: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class RepairAction:
    strategy: RepairStrategy = RepairStrategy.RETRY
    params: dict[str, Any] = field(default_factory=dict)

@dataclass
class Context:
    principal: str
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal": self.principal,
            "session_id": self.session_id,
            "metadata": dict(self.metadata),
        }

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self.metadata[key]

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self.metadata.get(key, default)

    def __contains__(self, key: object) -> bool:
        return hasattr(self, str(key)) or str(key) in self.metadata

@dataclass
class Criteria:
    checks: list[CheckSpec] = field(default_factory=list)

@dataclass
class Goal:
    id: str
    intent: str
    context: Context
    criteria: Criteria
    priority: int = 0

@dataclass
class Task:
    id: str
    step: Step
    agent: AgentId
    params: dict[str, Any] = field(default_factory=dict)

@dataclass
class Result:
    task_id: str
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class CheckResult:
    check: CheckSpec
    passed: bool
    detail: str = ""

@dataclass
class Verification:
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

@dataclass
class Observation:
    result: Result
    metrics: dict[str, Any] = field(default_factory=dict)
    side_effects: list[SideEffect] = field(default_factory=list)

@dataclass
class MemoryEntry:
    key: str
    value: Any = None
    scope: Scope = Scope.SESSION
    timestamp: float = field(default_factory=time.time)

@dataclass
class CommitRecord:
    id: str
    result: Result
    memory_refs: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

# Canonical MekongCoreRuntime Protocol lives in src.core.protocols
# This module only defines the concrete MekongCoreRuntimeImpl + supporting types.

_DEFAULT_CRITERIA = Criteria(checks=[CheckSpec(kind="exit_code", params={"expected": 0})])
_MAX_REPAIR_ATTEMPTS = 3


def _plan_has_dependencies(plan: Plan) -> bool:
    """Fast-path check: True if any step in the plan declares dependencies.

    Used by ``_run_goal`` to skip topological sorting for the common single-step
    ``mekong run`` path so behavior stays identical to sequential iteration.
    """
    return DAGScheduler(plan.steps).has_dependencies()


def _topological_task_order(tasks: list[Task]) -> list[Task]:
    """Return ``tasks`` reordered so every task follows its dependencies.

    Uses ``DAGScheduler`` to compute topological execution order from
    ``Step.dependencies`` produced by ``GoalEngineAdapter``.

    Degenerate cases (single-step plans, all ``dependencies=[]``) return tasks
    in their original order — preserving sequential parity.

    Raises:
        RuntimeError: if the dependency graph contains a cycle or unknown dependency.
    """
    if len(tasks) <= 1:
        return list(tasks)

    id_to_task: dict[str, Task] = {str(task.step.id): task for task in tasks}
    if len(id_to_task) != len(tasks):
        raise RuntimeError("duplicate task step ids in plan")

    sched = DAGScheduler(tasks)
    ordered_ids = sched.get_execution_order(strict=True)
    return [id_to_task[str(tid)] for tid in ordered_ids]


@dataclass
class _ExecResultLike:
    """Minimal ExecutionResult-shaped adapter for bridging core Result → RecipeVerifier.

    RecipeVerifier.verify() reads ``exit_code``, ``stdout``, ``stderr``, ``metadata``.
    Core Observation.result is a Result (output/error/metadata) — this adapter
    maps between the two without importing RecipeVerifier at module level.
    """

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _criteria_to_verifier_dict(criteria: Criteria) -> dict[str, Any]:
    """Translate core Criteria → RecipeVerifier criteria-dict.

    Supported CheckSpec mappings:
      - CheckSpec(kind="exit_code", params={"expected": N}) → {"exit_code": N}
      - CheckSpec(kind="output_pattern" | "output_contains", params={"pattern"|"text": P}) → {"output_contains": [P]}
      - CheckSpec(kind="output_not_contains", params={"pattern"|"text": P}) → {"output_not_contains": [P]}
      - CheckSpec(kind="file_exists", params={"path"|"filepath": F}) → {"file_exists": [F]}
      - CheckSpec(kind="file_not_exists", params={"path"|"filepath": F}) → {"file_not_exists": [F]}
    Unknown kinds are skipped (logged at debug).
    """
    out: dict[str, Any] = {}
    for spec in criteria.checks:
        if spec.kind == "exit_code":
            out["exit_code"] = spec.params.get("expected", 0)
        elif spec.kind in ("output_pattern", "output_contains"):
            pattern = spec.params.get("pattern") or spec.params.get("text")
            if pattern:
                out.setdefault("output_contains", []).append(pattern)
        elif spec.kind == "output_not_contains":
            pattern = spec.params.get("pattern") or spec.params.get("text")
            if pattern:
                out.setdefault("output_not_contains", []).append(pattern)
        elif spec.kind == "file_exists":
            filepath = spec.params.get("path") or spec.params.get("filepath")
            if filepath:
                out.setdefault("file_exists", []).append(filepath)
        elif spec.kind == "file_not_exists":
            filepath = spec.params.get("path") or spec.params.get("filepath")
            if filepath:
                out.setdefault("file_not_exists", []).append(filepath)
        else:
            logger.debug("verify: skipping unknown check kind=%s", spec.kind)
    return out


def _report_to_verification(report: Any) -> Verification:
    """Translate RecipeVerifier VerificationReport → core Verification.

    FAILED/WARNING checks surface as CheckResult entries; report.errors
    propagate to Verification.failures for backward compatibility.
    """
    checks: list[CheckResult] = []
    for check in report.checks:
        # VerificationCheck.name holds the original check kind (e.g. "exit_code").
        checks.append(
            CheckResult(
                check=CheckSpec(kind=check.name),
                passed=(check.status.value == "passed"),
                detail=check.message,
            )
        )
    failures: list[str] = list(report.errors or [])
    return Verification(passed=report.passed, checks=checks, failures=failures)

# Intent -> built-in agent keyword map (no LLM dependency). Mirrors the
# registry's _AGENT_ROLE_HINTS so classification stays in sync with the
# agents actually registered. Unmatched intent falls back to the runtime's
# own agent_id (e.g. "cli"), which is unregistered and delegates to the
# dispatcher's graceful-failure path — the same behavior as before.
# NOTE: "build" is deliberately NOT a keyword — goals like "deploy
# production build" must stay on the unregistered path.
_INTENT_AGENT_KEYWORDS: dict[str, str] = {
    "code": "cto",
    "refactor": "cto",
    "implement": "cto",
    "develop": "cto",
    "debug": "cto",
    "review": "cto",
    "marketing": "cmo",
    "campaign": "cmo",
    "brand": "cmo",
    "operations": "coo",
    "logistics": "coo",
    "workflow": "coo",
    "finance": "cfo",
    "budget": "cfo",
    "accounting": "cfo",
    "analysis": "cso",
    "analyze": "cso",
    "strategy": "cso",
    "competitive": "cso",
    "market": "cso",
    "plan": "planner",
    "roadmap": "planner",
    "architecture": "planner",
}


def _classify_intent(intent: str) -> str:
    """Map a goal intent to a registered built-in agent name.

    Returns an empty string when no keyword matches; the caller resolves
    the empty result to ``self._agent_id`` so the dispatcher's graceful
    failure path handles the goal unchanged.
    """
    lowered = (intent or "").lower()
    for keyword, agent_name in _INTENT_AGENT_KEYWORDS.items():
        if keyword in lowered:
            return agent_name
    return ""


class MekongCoreRuntimeImpl:
    def __init__(self, *, dispatcher, tool_registry, memory_store=None, memory_separation=None, billing=None, telemetry=None, llm_router=None, capability_bus=None, agent_id="default", governance=None, max_cost_usd: float | None = None, agent_registry=None, goal_engine: GoalEngine | None = None, verifier=None) -> None:
        """Construct the runtime.

        Memory model (SC7 convergence):
        - ``memory_store`` (default: ``MemoryStoreAdapter()``) is the **primary**
          remember() path — a single conformant adapter over the canonical
          YAML+vector store. Session-scoped writes use TTL=3600.
        - ``memory_separation`` is the **legacy** tier layer (None by default).
          It is only constructed when explicitly passed; the runtime no longer
          creates a separate ScopedMemoryStore backend for remember().

        Args:
            verifier: Optional RecipeVerifier instance. Defaults to
                ``RecipeVerifier(strict_mode=True)``. Imported inside __init__
                to avoid circular imports.
        """
        self._dispatcher = dispatcher
        self._tool_registry = tool_registry
        self._memory_store = memory_store or self._default_memory_store()
        self._memory_separation = memory_separation or self._default_memory_separation()
        self._billing = billing
        self._telemetry = telemetry or self._default_telemetry()
        self._llm_router = llm_router or self._default_llm_router()
        self._capability_bus = capability_bus
        self._agent_id = agent_id
        self._destroyed = False
        self._governance = governance
        self._repair_count: int = 0
        self._mission_id: str | None = None
        self._mission_tracer: Any | None = None
        # AUTONOMY_GAPS #6 — cost guard: hard ceiling on cumulative spend.
        self._max_cost_usd: float | None = max_cost_usd
        self._spent_cost_usd: float = 0.0
        # Lane E9: per-agent spend tracking keyed by agent name.
        # Reset on start_mission(). Used by the max_budget gate.
        self._agent_spend: dict[str, float] = {}
        # Lane E9: optional explicit agent registry. When provided, _resolve_agent_meta
        # uses it directly instead of the process-wide get_registry() singleton, so
        # tests (and callers that pre-register agents) control the lookup surface.
        self._agent_registry = agent_registry
        # GoalEngine for multi-step planning (SC6)
        self._goal_engine = goal_engine
        # RecipeVerifier — injected to allow test doubles; imported here to
        # avoid a circular import (verifier.py imports nothing from runtime_adapter).
        # Gap #4 (SC8): core runtime shares the same verifier as the harness.
        if verifier is None:
            from src.core.verifier import RecipeVerifier
            verifier = RecipeVerifier(strict_mode=True)
        self._verifier = verifier
        # Phase 5 (SC7): remember() writes through the conformant MemoryStoreAdapter
        # (_memory_store). Session-scoped keys (ttl=3600) are tracked here so
        # start_mission() can flush them via adapter.delete() — collapsing the
        # memory_separation tier layer onto the canonical conformant adapter.
        self._session_keys: set[str] = set()

    def _default_memory_store(self):
        from src.core.memory_store_adapter import MemoryStoreAdapter
        return MemoryStoreAdapter()

    def _default_telemetry(self):
        from src.core.telemetry_emitter import TelemetryEmitter
        return TelemetryEmitter()

    def _default_llm_router(self):
        from src.core.llm_router_adapter import LLMRouterAdapter
        return LLMRouterAdapter()

    def _default_memory_separation(self):
        # SC7 (Phase 6): the legacy tier layer is no longer constructed by
        # default. Callers that still want MemorySeparation pass it explicitly
        # via the constructor. The conformant MemoryStoreAdapter is the sole
        # remember() path going forward.
        return None

    # ── Lane E9: Agent policy enforcement helpers ───────────────────────

    _RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    _RISK_NAMES = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}

    def _resolve_agent_meta(self, agent_name: str):
        """Resolve the acting agent's AgentMeta from the registry.

        Returns None for unknown/unregistered agents — the existing
        behavior (capability-only classification) is preserved for those,
        so the run.py graceful-failure path never breaks. Only registered
        agents get the full 5-gate enforcement.

        Uses the explicit ``agent_registry`` constructor argument when set
        (tests / callers that pre-register agents); otherwise falls back to
        the process-wide ``get_registry()`` singleton.
        """
        if not agent_name:
            return None
        registry = self._agent_registry
        if registry is None:
            try:
                from src.core.agent_registry import get_registry

                registry = get_registry()
            except Exception:
                return None
        try:
            return registry.get_meta_obj(agent_name)
        except Exception:
            return None

    def _effective_risk(self, agent_risk: str, capability_risk: str) -> str:
        """Return the higher of the agent's and capability's risk levels.

        Unknown risk levels (not in the canonical set) are treated as
        CRITICAL — fail-closed, never default-allow.
        """
        agent_r = self._RISK_ORDER.get((agent_risk or "").upper())
        cap_r = self._RISK_ORDER.get((capability_risk or "").upper())
        if agent_r is None or cap_r is None:
            return "CRITICAL"
        return self._RISK_NAMES[max(agent_r, cap_r)]

    def start_mission(self, goal: str, tracer: Any = None, mission_id: str | None = None) -> str:
        """Start a new mission with optional tracer correlation.

        Clears any SESSION-tier memory left over from a prior run so each
        mission starts with a clean short-term context. When ``mission_id`` is
        supplied (e.g. from an external payload), the tracer is told to use it
        so step/finish calls land on the same record the caller expects.

        Also emits the mission start phase via the telemetry emitter for
        complete 3-phase trace correlation (Invariant 5).
        """
        self._mission_id = mission_id or f"mission_{uuid.uuid4().hex[:8]}"
        # Phase 5 (SC7): flush SESSION-tier memory via the conformant adapter.
        # _session_keys tracks every key remember() wrote with the SESSION TTL
        # (3600s); start_mission() removes them one-by-one through adapter.delete()
        # so each mission starts with a clean short-term context.
        try:
            self._flush_session_keys()
        except Exception:
            pass
        # AUTONOMY_GAPS #6 — cost ceiling is per-mission, not per-process.
        self._spent_cost_usd = 0.0
        # Lane E9: reset per-agent spend tracking per mission.
        self._agent_spend.clear()
        if tracer is not None:
            self._mission_tracer = tracer
            try:
                # Let the tracer own the correlation ID so step/finish calls
                # land on the same record it created.
                tracer_mission_id = tracer.start_mission(
                    goal, {"mission_id": self._mission_id}
                )
                if tracer_mission_id:
                    self._mission_id = tracer_mission_id
            except Exception:
                pass
        # Emit mission start phase via telemetry emitter (Invariant 5)
        if self._telemetry is not None and hasattr(self._telemetry, "emit_start"):
            self._telemetry.emit_start(self._mission_id, goal)
        logger.info("Mission started: %s goal=%s", self._mission_id, goal)
        return self._mission_id or ""

    def run(self, goal_text: str) -> Result:
        """Run the full lifecycle loop for a plain goal string.

        Mission-trace idempotency (single canonical mechanism): run() starts a
        mission ONLY when none is active (``self._mission_id is None``).
        Callers that already opened a mission keep ownership of it:

        - CLI wiring (``src/commands/run.py``) calls ``start_mission(goal,
          tracer=...)`` before ``run()`` so every step lands on the
          tracer-created mission record.
        - ``run_from_payload()`` calls ``_run_goal()`` directly and opens its
          own mission from the payload's pre-assigned id; it never re-enters
          ``run()``, so this guard cannot double-fire on the payload path.

        ``_finish_mission()`` intentionally does NOT reset ``_mission_id``:
        callers may still correlate against it after the loop (e.g. the Buzz
        callback path asserts the payload id survives). A second plain
        ``run()`` on the same instance therefore continues under the active
        mission id until the caller starts a new one.
        """
        if self._mission_id is None:
            self.start_mission(goal_text, tracer=self._mission_tracer)
        start = time.monotonic()
        ctx = Context(principal=self._agent_id, session_id=uuid.uuid4().hex[:16])
        g = self.goal(goal_text, ctx)
        return self._run_goal(g, start)

    def run_from_payload(self, payload: dict[str, Any]) -> Result:
        """Execute a goal parsed from an external payload (e.g. Buzz webhook).

        Wraps :class:`BuzzAdapter` so the runtime can accept structured goals
        with a callback URL and a pre-assigned mission id, without Buzz
        hardcoding leaking into the core loop.
        """
        from src.core.buzz_adapter import BuzzAdapter

        parsed = BuzzAdapter().receive_goal(payload)
        goal_text = parsed["text"]
        mission_id = parsed.get("mission_id")
        start = time.monotonic()
        ctx = Context(
            principal=self._agent_id,
            session_id=uuid.uuid4().hex[:16],
            metadata={"mission_id": mission_id, "callback_url": parsed.get("callback_url")},
        )
        g = self.goal(goal_text, ctx)
        if self._mission_id is None:
            self.start_mission(goal_text, tracer=self._mission_tracer, mission_id=mission_id)
        return self._run_goal(g, start)

    def _run_goal(self, goal: Goal, start: float) -> Result:
        self._record_stage("goal", {"goal_id": goal.id, "intent": goal.intent})
        p = self.plan(goal)
        self._record_stage("plan", {"plan_id": p.id, "steps": len(p.steps)})
        tasks = self.delegate(p)
        self._record_stage("delegate", {"tasks": len(tasks)})
        logger.info("Loop: goal=%s steps=%d tasks=%d", goal.id, len(p.steps), len(tasks))
        has_deps = _plan_has_dependencies(p)
        results: list[Result] = []
        if has_deps:
            results = self._run_dag_tasks(tasks, goal.criteria)
        else:
            for task in tasks:
                results.append(self._run_task_loop(task, goal.criteria))
        merged = self._merge_results(results)
        obs = self.observe(merged)
        self._record_stage("observe", {"has_error": merged.error is not None})
        entry = self.remember(obs)
        self._record_stage("remember", {"memory_key": entry.key})
        commit_rec = self.commit(merged)
        self._record_stage("commit", {"commit_id": commit_rec.id})
        self._finish_mission(merged)
        self._record_stage(
            "finish",
            {"outcome": "success" if merged.error is None else "failed"},
        )
        logger.info("Done in %.1fms commit=%s mem=%s", (time.monotonic() - start) * 1000, commit_rec.id, entry.key)
        return merged

    def goal(self, intent: str, context: Context | None = None) -> Goal:
        if context is None:
            context = Context(
                principal=self._agent_id,
                session_id=uuid.uuid4().hex[:16],
                metadata={"mission_id": self._mission_id},
            )
        return Goal(id=f"goal-{uuid.uuid4().hex[:12]}", intent=intent, context=context, criteria=_DEFAULT_CRITERIA, priority=0)

    def context(self, goal: Any = None) -> dict[str, Any]:
        """Extract or construct context metadata for the given goal.

        Conforms to :class:`src.core.protocols.MekongCoreRuntime`.
        """
        if goal is None:
            return {
                "principal": self._agent_id,
                "session_id": uuid.uuid4().hex[:16],
                "mission_id": self._mission_id,
                "metadata": {},
            }
        if hasattr(goal, "context"):
            ctx = getattr(goal, "context")
            if isinstance(ctx, dict):
                return dict(ctx)
            if hasattr(ctx, "to_dict") and callable(ctx.to_dict):
                data = ctx.to_dict()
                if "mission_id" not in data:
                    data["mission_id"] = self._mission_id
                return data
            if hasattr(ctx, "principal") and hasattr(ctx, "session_id"):
                return {
                    "principal": ctx.principal,
                    "session_id": ctx.session_id,
                    "metadata": getattr(ctx, "metadata", {}),
                    "mission_id": self._mission_id,
                }
        if isinstance(goal, dict):
            ctx_val = goal.get("context")
            if isinstance(ctx_val, dict):
                return dict(ctx_val)
            return {
                "principal": self._agent_id,
                "session_id": uuid.uuid4().hex[:16],
                "mission_id": goal.get("mission_id", self._mission_id),
                "metadata": goal.get("metadata", {}),
            }
        return {
            "principal": self._agent_id,
            "session_id": uuid.uuid4().hex[:16],
            "mission_id": self._mission_id,
            "metadata": {},
        }

    def _resolve_agent_name(self, intent: str) -> str:
        """Pick the agent name for this goal's intent.

        Registered built-in agents (cto/cmo/coo/cfo/cso/planner) are
        assigned by keyword classification; anything else keeps the
        runtime's own ``self._agent_id`` so the dispatcher's graceful
        failure path handles it unchanged (audit log below).
        """
        classified = _classify_intent(intent)
        return classified or self._agent_id

    def _audit_unknown_agent(self, agent_name: str, intent: str) -> None:
        """Best-effort audit log when an agent name is not registered.

        Does not raise — unknown agents fall back to the dispatcher's
        graceful failure path instead of crashing the mission loop.
        """
        if self._governance is None or not hasattr(self._governance, "record_audit"):
            return
        try:
            from src.core.governance import ActionClass, AuditEntry

            self._governance.record_audit(
                AuditEntry(
                    goal=intent,
                    action_class=ActionClass.SAFE.value,
                    approved=False,
                    result=f"unknown_agent:{agent_name}",
                )
            )
        except Exception:
            pass

    def plan(self, goal: Any, context: Any = None) -> Plan:
        if isinstance(goal, str):
            goal = self.goal(goal, context=context)
        elif isinstance(goal, dict):
            intent = goal.get("intent") or goal.get("goal") or goal.get("text", "")
            goal = self.goal(intent, context=context)
        agent_name = self._resolve_agent_name(goal.intent)
        # Multi-step only for registered built-in agents
        if agent_name in ("cto", "cmo", "coo", "cfo", "cso", "planner"):
            if self._goal_engine is None:
                from src.core.adapters.goal_engine_adapter import make_goal_engine_adapter
                self._goal_engine = make_goal_engine_adapter()
            multi_step_plan = self._goal_engine.decompose(goal.intent)
            multi_step_plan.id = f"plan-{uuid.uuid4().hex[:12]}"
            multi_step_plan.goal = goal.id
            multi_step_plan.status = PlanStatus.PENDING
            return multi_step_plan
        # Single-step fallback for "cli" and unknown agents
        step = Step(id="step-0", description=goal.intent, params={"goal_id": goal.id, "agent": agent_name})
        return Plan(id=f"plan-{uuid.uuid4().hex[:12]}", goal=goal.id, steps=[step], status=PlanStatus.IN_PROGRESS)

    # Role to registered agent mapping for multi-step plans
    _ROLE_AGENT_MAP = {
        "architect": "planner",
        "backend": "cto",
        "infra": "coo",
        "qa": "cto",
        "security": "cso",
        "docs": "cmo",
        "reviewer": "planner",
    }

    def delegate(self, plan: Plan) -> list[Task]:
        """Build tasks with explicit agent assignment.

        Payload contract: ``Task(step, agent=AgentId(name), params)``.
        For each step the agent name is resolved through the AgentRegistry
        (``get_meta_obj``); when the name is registered the dispatcher is
        expected to spawn the resolved ``AgentBase`` subclass via
        ``AgentBase.run()``. Unknown agents keep the current graceful
        behavior and are recorded in the audit log.

        For multi-step plans from GoalEngineAdapter, steps carry a "role"
        in params which is mapped to a registered agent via _ROLE_AGENT_MAP.
        Single-step fallback plans carry "agent" directly.
        """
        from src.core.agent_registry import get_registry

        registry = get_registry()
        tasks: list[Task] = []
        for step in plan.steps:
            # Multi-step: resolve agent from role; single-step: use agent from params
            role = step.params.get("role")
            if role and role in self._ROLE_AGENT_MAP:
                agent_name = self._ROLE_AGENT_MAP[role]
            else:
                agent_name = step.params.get("agent") or self._agent_id
            if registry.get_meta_obj(agent_name) is None:
                self._audit_unknown_agent(agent_name, step.description)
            tasks.append(
                Task(
                    id=f"task-{uuid.uuid4().hex[:8]}",
                    step=step,
                    agent=AgentId(name=agent_name),
                    params=dict(step.params),
                )
            )
        return tasks

    def execute(self, task: Task) -> Result:
        """Execute a task with safety gates: governance, cost check, retry limit."""
        tool_name = task.params.get("tool")
        capability_id = task.params.get("capability_id")
        goal_text = task.params.get("description", getattr(task.step, "description", ""))
        meta: dict[str, Any] = {"agent": task.agent.name}

        # Gate 1: Repair retry limit
        if self._repair_count >= 3:
            return Result(
                task_id=task.id,
                output=None,
                error="Max repair retries (3) exceeded",
                metadata=meta,
            )

        # Gate 2: Governance classification (goal-based — existing pattern)
        if self._governance is not None:
            try:
                from src.core.governance import ActionClass, Governance
                if isinstance(self._governance, Governance):
                    goal_text = task.params.get("description", task.step.description if hasattr(task.step, 'description') else "")
                    decision = self._governance.classify(goal_text)
                    if decision.action_class == ActionClass.FORBIDDEN:
                        self._record_audit(goal_text, decision, "blocked")
                        meta["gate_blocked"] = True
                        return Result(
                            task_id=task.id,
                            output=None,
                            error=f"Action forbidden: {decision.reason}",
                            metadata=meta,
                        )
                    if decision.action_class == ActionClass.REVIEW_REQUIRED:
                        if not self._governance.request_approval(goal_text, decision):
                            self._record_audit(goal_text, decision, "rejected")
                            meta["gate_blocked"] = True
                            return Result(
                                task_id=task.id,
                                output=None,
                                error=f"Action requires human approval: {decision.reason}",
                                metadata=meta,
                            )
                        self._record_audit(goal_text, decision, "approved")
            except ImportError:
                pass

        # Gate 2.5: Capability-based governance + AgentMeta policy enforcement (E9)
        # When task carries capability_id AND bus has that capability, classify by
        # effective risk = max(agent.risk_level, capability.risk_level), then enforce
        # the acting agent's policy fields BEFORE any dispatch happens:
        #   risk_level → allowed_tools → max_budget → max_iterations → approval_policy
        # allowed_tools runs before approval so a disallowed capability is never
        # surfaced to a human approver. Spend is only recorded after the dispatch
        # succeeds (see agent_spend_delta below).
        agent_spend_delta: tuple[str, float] | None = None
        if capability_id and self._capability_bus is not None and self._governance is not None:
            try:
                from src.core.governance import ActionClass, Governance
                if isinstance(self._governance, Governance):
                    cap = self._capability_bus.get(capability_id)
                    if cap is not None:
                        # Resolve acting agent's meta (may be None for unknown agents)
                        agent_name = task.agent.name if task.agent else None
                        agent_meta = self._resolve_agent_meta(agent_name) if agent_name else None

                        # Compute effective risk for governance classification
                        if agent_meta is not None:
                            effective_risk = self._effective_risk(agent_meta.risk_level, cap.risk_level)
                        else:
                            # Unknown/unregistered agent → preserve current behavior
                            # (capability-only classification, no extra gates) BUT still
                            # fail-closed on an unknown capability risk level so an
                            # invalid risk string can never default-allow.
                            effective_risk = cap.risk_level if cap.risk_level in self._RISK_ORDER else "CRITICAL"

                        decision = self._governance.classify_risk(effective_risk)

                        # Gate 1: risk_level → FORBIDDEN blocks immediately
                        if decision.action_class == ActionClass.FORBIDDEN:
                            self._record_audit(capability_id, decision, "blocked")
                            meta["gate_blocked"] = True
                            return Result(
                                task_id=task.id,
                                output=None,
                                error=f"Capability forbidden: {decision.reason}",
                                metadata=meta,
                            )

                        # Gate 2: allowed_tools — reject capabilities not in the
                        # agent's allowlist. Empty list or ["*"] = unrestricted.
                        if agent_meta is not None and agent_meta.allowed_tools:
                            allowed = agent_meta.allowed_tools
                            if "*" not in allowed and capability_id not in allowed:
                                meta["gate_blocked"] = True
                                return Result(
                                    task_id=task.id,
                                    output=None,
                                    error=f"Capability '{capability_id}' not allowed for agent '{agent_name}' (allowed_tools: {allowed})",
                                    metadata=meta,
                                )

                        # Gate 3: max_budget — per-agent cost guard before execute
                        if agent_meta is not None and agent_meta.max_budget is not None:
                            cap_cost = float(cap.cost or 0.0)
                            agent_key = agent_name or "unknown"
                            current_spent = self._agent_spend.get(agent_key, 0.0)
                            projected = current_spent + cap_cost
                            if projected > agent_meta.max_budget:
                                meta["gate_blocked"] = True
                                return Result(
                                    task_id=task.id,
                                    output=None,
                                    error=f"Agent budget exceeded: ${projected:.4f} > ${agent_meta.max_budget:.4f} (spent ${current_spent:.4f}, capability cost ${cap_cost:.4f})",
                                    metadata=meta,
                                )
                            # Deferred: recorded only after successful dispatch.
                            agent_spend_delta = (agent_key, cap_cost)

                        # Gate 4: max_iterations — cap repair iterations for this agent
                        if agent_meta is not None and agent_meta.max_iterations is not None:
                            if self._repair_count >= agent_meta.max_iterations:
                                meta["gate_blocked"] = True
                                return Result(
                                    task_id=task.id,
                                    output=None,
                                    error=f"Agent iteration cap exceeded: {self._repair_count} >= {agent_meta.max_iterations}",
                                    metadata=meta,
                                )

                        # Gate 5: approval_policy — DENY always rejects; MANUAL and
                        # AUTO both route REVIEW_REQUIRED through request_approval()
                        # (AUTO can be bypassed via GOVERNANCE_AUTO_APPROVE inside
                        # governance.request_approval itself).
                        if agent_meta is not None and agent_meta.approval_policy == "DENY":
                            self._record_audit(capability_id, decision, "rejected")
                            meta["gate_blocked"] = True
                            return Result(
                                task_id=task.id,
                                output=None,
                                error=f"Agent approval policy DENY: capability '{capability_id}' denied",
                                metadata=meta,
                            )
                        if decision.action_class == ActionClass.REVIEW_REQUIRED:
                            if not self._governance.request_approval(capability_id, decision):
                                self._record_audit(capability_id, decision, "rejected")
                                meta["gate_blocked"] = True
                                return Result(
                                    task_id=task.id,
                                    output=None,
                                    error=f"Capability requires human approval: {decision.reason}",
                                    metadata=meta,
                                )
                            self._record_audit(capability_id, decision, "approved")
            except ImportError:
                pass

        # Gate 3: Cost estimate (best-effort — warn but don't block)
        if self._llm_router is not None and hasattr(self._llm_router, "estimate_cost"):
            try:
                goal_text = task.params.get("description", task.step.description if hasattr(task.step, 'description') else "")
                tokens_est = max(len(str(goal_text)) // 4, 100)
                cost = self._llm_router.estimate_cost("default", tokens_est)
                meta["estimated_cost"] = cost
            except Exception:
                pass

        # Gate 3.5: Cost limit enforcement (AUTONOMY_GAPS #6)
        guard = self._check_cost_guard(meta.get("estimated_cost"))
        if guard is not None:
            meta["gate_blocked"] = True
            return Result(task_id=task.id, output=None, error=guard, metadata=meta)

        try:
            if tool_name and hasattr(self._tool_registry, "execute"):
                output = self._tool_registry.execute(tool_name, task.params)
            elif hasattr(self._dispatcher, "dispatch"):
                output = self._dispatcher.dispatch(task, task.agent)
            else:
                output = {"status": "noop", "task_id": task.id}
            if self._governance is not None and hasattr(self._governance, "record_audit"):
                try:
                    from src.core.governance import AuditEntry
                    self._governance.record_audit(
                        AuditEntry(goal=goal_text, action_class="safe", approved=True, result="executed")
                    )
                except Exception:
                    pass
            # Lane E9: record per-agent spend only after successful dispatch.
            if agent_spend_delta is not None:
                agent_key, cap_cost = agent_spend_delta
                self._agent_spend[agent_key] = self._agent_spend.get(agent_key, 0.0) + cap_cost
            # Surface the dispatcher's failure into this Result so the repair
            # loop can trigger and the mission outcome reflects reality.
            # Without this, a failed dispatch (e.g. a non-zero shell exit) was
            # silently folded into a "success" Result that the loop verified
            # as passed — masking every agent error under a happy path.
            # Only an explicit error field is propagated; "success"/"noop"
            # remain error-free so a no-op dispatch never breaks the loop.
            dispatch_error: str | None = None
            if isinstance(output, dict):
                err_val = output.get("error")
                dispatch_error = str(err_val) if err_val else None
            return Result(task_id=task.id, output=output, error=dispatch_error, metadata=meta)
        except Exception as exc:
            logger.error("Execute failed task=%s: %s", task.id, exc)
            return Result(task_id=task.id, error=str(exc), metadata=meta)

    def observe(self, result: Result) -> Observation:
        metrics: dict[str, Any] = {"has_error": result.error is not None}
        # AUTONOMY_GAPS #11: cost is estimated in execute() but was discarded.
        # Propagate it into the observation so it lands in telemetry + memory.
        estimated = result.metadata.get("estimated_cost")
        if estimated is not None:
            metrics["estimated_cost"] = estimated
        # TelemetryEmitter routes task_completed → emit_step() internally,
        # so the 3-phase trace (start/step/finish) is produced automatically.
        if self._telemetry is not None:
            self._telemetry.emit({
                "event_type": "task_completed",
                "metric": 1.0,
                "estimated_cost": estimated,
                "mission_id": self._mission_id,
            })
        se: list[SideEffect] = []
        if result.error:
            se.append(SideEffect(kind="error", target=result.task_id, data={"error": result.error}))
        return Observation(result=result, metrics=metrics, side_effects=se)

    def verify(self, observation: Observation, criteria: Criteria) -> Verification:
        # Gap #4 (SC8): delegate to RecipeVerifier for the same verdict the
        # harness produces. Falls back to the legacy no-criteria behavior when
        # the criteria-dict is empty so existing callers are unaffected.
        criteria_dict = _criteria_to_verifier_dict(criteria)
        if not criteria_dict:
            # Empty criteria: preserve legacy behavior — passed iff no error.
            return Verification(passed=observation.result.error is None)

        result = observation.result
        exec_result_like = _ExecResultLike(
            exit_code=0 if result.error is None else 1,
            stdout=str(result.output) if result.output is not None else "",
            stderr=result.error or "",
            metadata=result.metadata or {},
        )
        report = self._verifier.verify(cast(Any, exec_result_like), criteria_dict)
        return _report_to_verification(report)

    def repair(self, verification: Verification) -> RepairAction:
        """Attempt to repair a failed result. Abort after 3 retries."""
        if self._repair_count >= 3:
            return RepairAction(strategy=RepairStrategy.ESCALATE)
        self._repair_count += 1
        if verification.failures:
            has_error = any("error" in f.lower() for f in verification.failures)
            return RepairAction(strategy=RepairStrategy.RETRY if has_error else RepairStrategy.FALLBACK)
        return RepairAction(strategy=RepairStrategy.RETRY)

    def remember(self, observation: Observation) -> MemoryEntry:
        key = f"obs-{observation.result.task_id}"
        value = {"task_id": observation.result.task_id, "error": observation.result.error, "metrics": observation.metrics}
        entry = MemoryEntry(key=key, value=value, scope=Scope.SESSION)
        # Phase 5 (SC7): writes route through the conformant MemoryStoreAdapter
        # (_memory_store) with TTL=3600 (SESSION-tier default). This collapses the
        # memory_separation tier layer onto the single conformant adapter — the
        # dead _memory_store attribute is now the sole write path (LOW-3 fix).
        payload = json.dumps(value, default=str).encode("utf-8")
        try:
            if self._memory_store is not None:
                self._memory_store.store(key, payload, ttl=3600)
                self._session_keys.add(key)
        except Exception:
            # Fallback: best-effort legacy path. Only reachable when the
            # caller injected a MemorySeparation instance; the default runtime
            # no longer constructs one, so this branch is effectively dormant.
            if self._memory_separation is not None:
                try:
                    self._memory_separation.store(
                        key, payload, tier=MemoryTier.SESSION,
                    )
                    self._session_keys.add(key)
                except Exception:
                    logger.warning("remember() write failed key=%s", key)
            else:
                logger.warning("remember() write failed key=%s", key)
        return entry

    def flush_session(self) -> int:
        """Clear all SESSION-tier memory. Returns count deleted.

        Phase 5 (SC7): delegates to the adapter-based flush so the runtime's
        session memory is cleared through the conformant MemoryStoreAdapter.
        Returns the number of keys cleared (best-effort).
        """
        try:
            return self._flush_session_keys()
        except Exception:
            return 0

    def _flush_session_keys(self) -> int:
        """Delete every SESSION-tier key through the conformant adapter.

        Iterates the runtime's tracked session keys and removes each via
        adapter.delete(). The canonical adapter's delete() removes all entries
        whose goal matches the key, which is exactly the set remember() wrote.
        Returns the count of keys cleared.
        """
        cleared = 0
        if self._memory_store is not None:
            keys = list(self._session_keys)
            for key in keys:
                try:
                    deleted = self._memory_store.delete(key)
                    if deleted:
                        cleared += 1
                except Exception:
                    logger.warning("session flush failed key=%s", key)
            self._session_keys.clear()
            if hasattr(self._memory_store, "prune_expired"):
                try:
                    self._memory_store.prune_expired()
                except Exception:
                    pass

        if self._memory_separation is not None and hasattr(self._memory_separation, "flush_session"):
            try:
                cleared += self._memory_separation.flush_session()
            except Exception:
                pass

        return cleared

    def commit(self, result: Result) -> CommitRecord:
        record = CommitRecord(id=f"commit-{uuid.uuid4().hex[:12]}", result=result)
        if result.error is None and self._billing is not None and hasattr(self._billing, "record_usage"):
            try:
                self._billing.record_usage(self._agent_id, 0, "default", "run")
                if hasattr(self._billing, "check_quota"):
                    self._billing.check_quota(self._agent_id)
            except Exception as exc:
                logger.warning("Billing record_usage failed: %s", exc)
        if self._telemetry is not None:
            self._telemetry.emit({"event_type": "run_completed", "task_id": result.task_id, "error": result.error, "mission_id": self._mission_id})
        return record

    def _is_cancelled(self) -> bool:
        """Cooperative-cancellation probe (guarded external seam).

        External adapters (e.g. BuzzRuntimeAdapter.cancel_mission) may set
        ``_cancel_requested`` on the runtime between steps. Default runtimes
        never set it, so this is a strict no-op for every existing caller.
        """
        return bool(getattr(self, "_cancel_requested", False))

    def _cancelled_result(self, task: Task, prior: Result | None = None) -> Result:
        return Result(
            task_id=prior.task_id if prior else task.id,
            output=prior.output if prior else None,
            error="mission cancelled",
            metadata={**(prior.metadata if prior else {}), "cancelled": True},
        )

    def _run_dag_tasks(self, tasks: list[Task], criteria: Criteria) -> list[Result]:
        """Execute tasks respecting DAG dependency order, propagating failures downstream.

        When a task's verify/repair cycle cannot recover (exhausted retries,
        ESCALATE/ROLLBACK strategy), ``DAGScheduler.mark_failed`` is called so
        all downstream dependents are cancelled and receive a ``_cancelled_result``
        instead of being executed with broken upstream state.

        For tasks with no deps (or all deps satisfied), order follows topological
        sort already embedded in the scheduler's ``get_execution_order``.

        Returns results in the same topological order as task input.
        """
        ordered = _topological_task_order(tasks)
        if len(ordered) <= 1:
            return [self._run_task_loop(t, criteria) for t in ordered]

        sched: DAGScheduler = DAGScheduler(ordered)
        results: dict[str, Result] = {}

        # Walk in topological order; a task whose key is in sched.cancelled_steps
        # was skipped due to an upstream failure — produce a cancelled result.
        for task in ordered:
            step_order = _get_order(task)
            step_key = str(task.step.id)
            if step_order in sched.cancelled_steps or step_key in sched.cancelled_steps:
                logger.warning("DAG: skipping cancelled task=%s (upstream failed)", task.id)
                results[step_key] = self._cancelled_result(task)
                continue
            result = self._run_task_loop(task, criteria)
            results[step_key] = result
            # Determine success: no error and not gate-blocked
            failed = result.error is not None and not result.metadata.get("gate_blocked", False)
            if failed:
                sched.mark_failed(step_order)
                logger.warning(
                    "DAG: task=%s failed, cancelling downstream dependents", task.id
                )
            else:
                sched.mark_completed(step_order)

        return [results[str(t.step.id)] for t in ordered]

    def _run_task_loop(self, task: Task, criteria: Criteria) -> Result:
        attempts = 0
        if self._is_cancelled():
            return self._cancelled_result(task)
        result = self.execute(task)
        while attempts < _MAX_REPAIR_ATTEMPTS:
            if self._is_cancelled():
                logger.warning("Mission cancelled task=%s", task.id)
                return self._cancelled_result(task, result)
            obs = self.observe(result)
            verification = self.verify(obs, criteria)
            self._trace_step(task, result, verification)
            # Gate verdicts (governance block, cost ceiling) are deterministic
            # policy decisions, not transient failures — retrying cannot change
            # the outcome and would mask the real reason under a retry-limit
            # error, so surface them immediately.
            if verification.passed or result.metadata.get("gate_blocked", False):
                return result
            attempts += 1
            logger.warning("Verify failed task=%s attempt=%d: %s", task.id, attempts, verification.failures)
            action = self.repair(verification)
            if action.strategy in (RepairStrategy.ESCALATE, RepairStrategy.ROLLBACK):
                logger.error("Repair %s task=%s", action.strategy.value, task.id)
                return result
            result = self.execute(task)
        logger.error("Max repair attempts exceeded task=%s", task.id)
        return result

    def _check_cost_guard(self, cost_estimate: Any) -> str | None:
        """Return an error string when the cost ceiling would be breached.

        Returns None when execution may proceed. Never raises — a broken
        cost estimate must not break the loop.
        """
        if self._max_cost_usd is None:
            return None
        try:
            amount = float(cost_estimate.get("cost_usd", 0.0)) if isinstance(cost_estimate, dict) else 0.0
        except Exception:
            amount = 0.0
        projected = self._spent_cost_usd + amount
        if projected > self._max_cost_usd:
            return (
                f"Cost ceiling exceeded: ${projected:.4f} > ${self._max_cost_usd:.4f} "
                f"(spent ${self._spent_cost_usd:.4f}, estimated ${amount:.4f})"
            )
        self._spent_cost_usd = projected
        return None

    def _record_audit(self, goal_text: str, decision: Any, outcome: str) -> None:
        """Push a governance audit entry. Best-effort — never breaks the loop."""
        if self._governance is None or not hasattr(self._governance, "record_audit"):
            return
        try:
            from src.core.governance import AuditEntry
            self._governance.record_audit(
                AuditEntry(
                    goal=goal_text,
                    action_class=decision.action_class.value,
                    approved=outcome in ("approved", "executed"),
                    result=outcome,
                )
            )
        except Exception:
            pass

    def _trace_step(self, task: Task, result: Result, verification: Verification) -> None:
        """Push a step record into the mission tracer when one is attached."""
        if self._mission_tracer is None or self._mission_id is None:
            return
        try:
            self._mission_tracer.log_step(
                self._mission_id,
                task.id,
                {
                    "output": result.output,
                    "error": result.error,
                    "passed": verification.passed,
                    "failures": verification.failures,
                },
            )
        except Exception:
            # Tracing must never break the runtime loop.
            pass

    def _finish_mission(self, result: Result) -> None:
        """Close the mission trace with the final outcome."""
        if self._mission_tracer is None or self._mission_id is None:
            return
        try:
            outcome = "success" if result.error is None else "failed"
            self._mission_tracer.end_mission(self._mission_id, outcome)
        except Exception:
            pass

    def _record_stage(self, stage: str, metadata: dict[str, Any] | None = None) -> None:
        """Push a high-level lifecycle stage onto the attached mission tracer.

        Lane E8: the canonical runtime's ``_run_goal`` is the single source of
        truth for the 10-stage agent lifecycle (Goal → Plan → Delegate →
        Execute → Observe → Remember → Commit → Finish). Stages are recorded
        here so the tracer exposes an ordered overlay on top of its existing
        per-task ``log_step`` records — the CLI ``mekong cook`` summary and the
        E2E hermetic test both assert on this sequence.

        Best-effort: a tracer without ``record_stage`` (older callers) is a
        silent no-op, so this is fully backward compatible.
        """
        if self._mission_tracer is None:
            return
        try:
            recorder = getattr(self._mission_tracer, "record_stage", None)
            if recorder is not None:
                recorder(stage, metadata)
        except Exception:
            # Tracing must never break the runtime loop.
            pass

    @staticmethod
    def _evaluate_check(spec: CheckSpec, observation: Observation) -> bool:
        if spec.kind == "exit_code":
            return observation.result.error is None
        if spec.kind == "output_pattern":
            pattern = spec.params.get("pattern", "")
            return pattern in str(observation.result.output) if pattern else True
        return True

    @staticmethod
    def _merge_results(results: list[Result]) -> Result:
        if len(results) == 1:
            return results[0]
        errors = [r.error for r in results if r.error]
        return Result(task_id="merged", output=[r.output for r in results], error="; ".join(errors) if errors else None, metadata={"task_count": len(results)})

    def health(self) -> dict[str, Any]:
        """Return runtime health status."""
        try:
            llm_ok = self._llm_router.health() if self._llm_router else {"status": "not_set"}
            return {
                "status": "ok",
                "agent_id": self._agent_id,
                "destroyed": self._destroyed,
                "llm_router": llm_ok,
                "has_billing": self._billing is not None,
                "has_capability_bus": self._capability_bus is not None,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def destroy(self) -> dict[str, Any]:
        """Tear down runtime, release resources."""
        self._destroyed = True
        self._memory_store = None
        self._memory_separation = None
        self._telemetry = None
        self._llm_router = None
        self._capability_bus = None
        self._billing = None
        self._mission_id = None
        self._mission_tracer = None
        return {"status": "destroyed", "agent_id": self._agent_id}