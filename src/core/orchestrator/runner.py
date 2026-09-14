# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""
RecipeOrchestrator — main Plan -> Execute -> Verify coordinator.
"""

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

# Runtime imports — these names are used directly in __init__ and other methods.
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from ..planner import RecipePlanner, PlanningContext
from ..verifier import RecipeVerifier
from ..executor import RecipeExecutor  # noqa: F401 — re-export for test patching
from ..parser import Recipe, RecipeStep  # noqa: F401
from ..telemetry import TelemetryCollector
from ..memory_canonical import MemoryEntry, MemoryStore
from ..nlu import IntentClassifier
from ..execution_history import ExecutionHistory, ExecutionEvent, EventKind
from ..retry_policy import RetryPolicy
from ..constitution import Constitution, ConstitutionalReview as ConReview
from ..workflow_state import WorkflowState, WorkflowStatus, StepStatus
from ..dag_scheduler import DAGScheduler, validate_dag
from .display import display_report, format_status
from .models import OrchestrationResult, OrchestrationStatus, StepResult
from .rollback import handle_failure

if TYPE_CHECKING:
    from src.providers.llm.client import LLMClient


class RecipeOrchestrator:
    """
    Coordinates Plan -> Execute -> Verify workflow.

    This is the main entry point for executing goals with full
    planning, execution, and verification pipeline.
    """

    def __init__(
        self,
        llm_client: Optional["LLMClient"] = None,
        strict_verification: bool = True,
        enable_rollback: bool = True,
        use_swarm: bool = False,
        retry_policy: Optional[RetryPolicy] = None,
        constitution: Optional[Constitution] = None,
        constitutional_mode: str = "audit",  # "monitor", "audit", "enforce"
    ) -> None:
        self.planner = RecipePlanner(llm_client=llm_client)
        self.verifier = RecipeVerifier(strict_mode=strict_verification)
        self.console = Console()
        self.enable_rollback = enable_rollback
        self.telemetry = TelemetryCollector()
        self.memory = MemoryStore()
        self.nlu = IntentClassifier(llm_client=llm_client)
        self.retry_policy = retry_policy or RetryPolicy()
        self.history = ExecutionHistory()
        self.logger = logging.getLogger(self.__class__.__name__)

        # Constitutional AI
        self.constitution = constitution or Constitution(llm_client=llm_client)
        self.constitutional_mode = constitutional_mode

        # AGI v2 subsystems (lazy import so absent engines don't break the orchestrator)
        from .agi import AGIComponents as _AGIComponents

        self._agi = _AGIComponents(llm_client=llm_client)
        # Keep backward-compat aliases used in tests/other code
        self._reflection = self._agi.reflection
        self._world_model = self._agi.world_model
        self._tool_registry = self._agi.tool_registry
        self._collaboration = self._agi.collaboration
        self._code_evolution = self._agi.code_evolution
        self._vector_memory = self._agi.vector_memory

        # Swarm dispatcher (optional)
        if use_swarm:
            from ..swarm import SwarmDispatcher, SwarmRegistry
            self.dispatcher: Optional[Any] = SwarmDispatcher(SwarmRegistry())
        else:
            self.dispatcher = None

        # BMAD loader
        self.bmad_loader: Optional[Any] = None
        try:
            from packages.core.bmad.loader import BMADWorkflowLoader
            self.bmad_loader = BMADWorkflowLoader()
        except ImportError:
            self.console.print("[yellow]Warning: BMAD loader not available[/yellow]")

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run_from_goal(
        self,
        goal: str,
        context: Optional[PlanningContext] = None,
        progress_callback: Optional[Callable[..., None]] = None,
    ) -> OrchestrationResult:
        """Execute complete workflow from high-level goal (PLAN -> EXECUTE -> VERIFY)."""
        self.console.print(
            Panel(
                f"[bold]Goal:[/bold] {goal}",
                title="🎯 Mekong Orchestrator",
                border_style="cyan",
            )
        )

        goal_start_time = time.time()
        self.telemetry.start_trace(goal)

        # AGI pre-execution hints + world snapshot
        world_before = self._agi.print_pre_execution_hints(goal, self.console)

        # NLU Phase — try direct recipe match
        result = self._try_nlu_shortcut(
            goal, progress_callback, goal_start_time, world_before
        )
        if result is not None:
            return result

        # PHASE 1: PLAN
        self.console.print("\n[bold yellow]📋 PHASE 1: PLANNING[/bold yellow]")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            task = progress.add_task("Generating execution plan...", total=None)
            recipe = self.planner.plan(goal, context)
            progress.update(task, completed=True)

        plan_issues = self.planner.validate_plan(recipe)
        if plan_issues:
            self.console.print("[yellow]⚠️ Plan validation warnings:[/yellow]")
            for issue in plan_issues:
                self.console.print(f" • {issue}")

        # Constitutional review of plan (PLAN hook)
        plan_constitutional_review = self._review_plan_constitution(recipe, goal)
        if plan_constitutional_review.blocked:
            self.console.print("[bold red]🚫 Plan blocked by Constitutional AI[/bold red]")
            self.console.print(f"Score: {plan_constitutional_review.overall_score:.2f}")
            for result in plan_constitutional_review.principle_results:
                if not result.passed:
                    self.console.print(f" • {result.principle.value}: {result.reason}")
            if self.constitutional_mode == "enforce":
                raise ValueError(
                    f"Plan failed constitutional review "
                    f"(score={plan_constitutional_review.overall_score:.2f})"
                )
            else:
                self.console.print("[yellow]⚠️ Continuing in non-enforce mode[/yellow]")

        self.console.print(f"[green]✓[/green] Generated {len(recipe.steps)} steps")
        self._record_constitutional_metric(
            phase="plan",
            score=plan_constitutional_review.overall_score,
            recipe_name=recipe.name,
        )

        # PHASE 2 & 3: EXECUTE -> VERIFY
        result = self.run_from_recipe(recipe, progress_callback=progress_callback)

        # Attach plan constitutional score
        result.constitutional_plan_score = plan_constitutional_review.overall_score

        # Calculate average step constitutional score
        step_scores = [
            sr.constitutional_score
            for sr in result.step_results
            if sr.constitutional_score is not None
        ]
        if step_scores:
            result.constitutional_average_step_score = sum(step_scores) / len(
                step_scores
            )

        # Overall compliance (plan + average steps)
        if result.constitutional_plan_score and result.constitutional_average_step_score:
            combined = (
                result.constitutional_plan_score + result.constitutional_average_step_score
            ) / 2
            result.constitutional_compliant = combined >= 0.7

        self.telemetry.finish_trace()
        duration_ms = (time.time() - goal_start_time) * 1000
        self._record_memory(goal, result, duration_ms)
        self._post_execution_agi(
            goal, result.status.value, duration_ms, world_before, result.errors
        )

        return result

    def run_from_recipe(
        self,
        recipe: Recipe,
        progress_callback: Optional[Callable[..., None]] = None,
    ) -> OrchestrationResult:
        """Execute existing recipe with verification (EXECUTE -> VERIFY)."""
        workflow_id = uuid.uuid4().hex[:12]
        result = OrchestrationResult(
            status=OrchestrationStatus.SUCCESS,
            recipe=recipe,
            total_steps=len(recipe.steps),
        )

        wf_state = WorkflowState(workflow_id=workflow_id)
        wf_state.register_steps(len(recipe.steps))
        wf_state.transition(WorkflowStatus.RUNNING)

        self.history.append(
            ExecutionEvent.create(
                EventKind.WORKFLOW_STARTED,
                workflow_id,
                data={"recipe": recipe.name, "steps": len(recipe.steps)},
            )
        )

        self.console.print(
            "\n[bold yellow]⚙️ PHASE 2: EXECUTION & VERIFICATION[/bold yellow]"
        )

        executor = RecipeExecutor(recipe)

        # DAG parallel path
        dag = DAGScheduler(recipe.steps)
        if dag.has_dependencies():
            return self._run_dag(recipe, executor, dag, result, workflow_id, wf_state)

        # Sequential path
        self._run_sequential(
            recipe, executor, result, workflow_id, wf_state, progress_callback
        )

        # Finalize
        self._finalize_workflow(result, workflow_id, wf_state)
        self.history.persist(workflow_id)
        self._display_report(result)
        return result

    def run_bmad_workflow(
        self, workflow_id: str, context: Optional[Dict[str, Any]] = None
    ) -> OrchestrationResult:
        """Execute a BMAD workflow by ID."""
        if not self.bmad_loader:
            raise RuntimeError("BMAD loader not available")

        workflow = self.bmad_loader.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow not found: {workflow_id}")

        step = RecipeStep(
            order=1,
            title=f"Execute {workflow.name}",
            description=f"# BMAD Workflow: {workflow_id}",
            params={"workflow_id": workflow_id, "context": context or {}},
        )
        recipe = Recipe(
            name=workflow.name,
            description=workflow.description,
            steps=[step],
            metadata={"agent_type": workflow.agent_type, "source": "bmad"},
        )
        return self.run_from_recipe(recipe)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_nlu_shortcut(
        self,
        goal: str,
        progress_callback: Optional[Callable[..., None]],
        goal_start_time: float,
        world_before: Optional[Any],
    ) -> Optional[OrchestrationResult]:
        """Try to match goal to a known recipe via NLU. Returns result or None."""
        intent_result = self.nlu.classify(goal)
        if not (intent_result.confidence > 0.7 and intent_result.suggested_recipe):
            return None

        from ..smart_router import SmartRouter

        router = SmartRouter(memory_store=self.memory)
        route = router.route(intent_result)
        if not (route.action == "recipe" and route.recipe_path):
            return None

        from ..parser import RecipeParser
        from pathlib import Path as _Path

        try:
            recipe = RecipeParser().parse(_Path(route.recipe_path))
            self.console.print(
                f"[green]NLU:[/green] Matched recipe '{route.recipe_name}'"
            )
            result = self.run_from_recipe(recipe, progress_callback=progress_callback)
            self.telemetry.finish_trace()
            duration_ms = (time.time() - goal_start_time) * 1000
            self._record_memory(goal, result, duration_ms)
            self._post_execution_agi(
                goal, result.status.value, duration_ms, world_before, result.errors
            )
            return result
        except Exception:
            return None

    def _record_memory(
        self, goal: str, result: OrchestrationResult, duration_ms: float
    ) -> None:
        entry = MemoryEntry(
            goal=goal,
            status=result.status.value,
            duration_ms=duration_ms,
            error_summary="; ".join(result.errors[:3]) if result.errors else "",
            recipe_used=result.recipe.name if result.recipe else "",
        )
        self.memory.record(entry)

    def _post_execution_agi(
        self,
        goal: str,
        status: str,
        duration_ms: float,
        world_before: Optional[Any],
        errors: List[str],
    ) -> None:
        """Run post-execution AGI pipeline using current component references."""
        # Use self._reflection / _world_model etc. directly so tests can
        # override them by setting orch._reflection = mock after construction.
        from .agi import AGIComponents as _A

        tmp = _A.__new__(_A)
        tmp.reflection = self._reflection
        tmp.world_model = self._world_model
        tmp.tool_registry = self._tool_registry
        tmp.collaboration = self._collaboration
        tmp.code_evolution = self._code_evolution
        tmp.vector_memory = self._vector_memory
        tmp.run_post_execution(goal, status, duration_ms, world_before, errors, self.console)

    def _run_dag(
        self,
        recipe: Recipe,
        executor: RecipeExecutor,
        dag: DAGScheduler,
        result: OrchestrationResult,
        workflow_id: str,
        wf_state: WorkflowState,
    ) -> OrchestrationResult:
        """Run steps in DAG parallel mode."""
        cycle_err = validate_dag(recipe.steps)
        if cycle_err:
            result.status = OrchestrationStatus.FAILED
            result.errors.append(cycle_err)
            self._display_report(result)
            return result

        self.console.print("[dim]DAG mode: parallel execution enabled[/dim]")

        def _dag_executor(step: RecipeStep) -> StepResult:
            return self._execute_and_verify_step(executor, step, workflow_id, wf_state)

        def _on_dag_complete(order: int, dag_result: Any) -> None:
            if dag_result.success:
                result.completed_steps += 1
                self.console.print(f"[green]✓[/green] Step {order} passed")
            else:
                result.failed_steps += 1
                self.console.print(f"[red]✗[/red] Step {order} failed")

        dag_results = dag.execute_all(_dag_executor, _on_dag_complete)

        for order in sorted(dag_results):
            dr = dag_results[order]
            if dr.result:
                result.step_results.append(dr.result)
            if not dr.success:
                result.status = OrchestrationStatus.PARTIAL
            if dr.error:
                result.errors.append(f"Step {order}: {dr.error}")

        for cancelled_order in dag.cancelled_steps:
            result.errors.append(
                f"Step {cancelled_order}: cancelled (upstream failure)"
            )

        if result.failed_steps == 0 and not dag.cancelled_steps:
            result.status = OrchestrationStatus.SUCCESS
            wf_state.transition(WorkflowStatus.COMPLETED)
            self.history.append(
                ExecutionEvent.create(
                    EventKind.WORKFLOW_COMPLETED,
                    workflow_id,
                    data={"success_rate": result.success_rate},
                )
            )
        else:
            wf_state.transition(WorkflowStatus.FAILED)
            self.history.append(
                ExecutionEvent.create(
                    EventKind.WORKFLOW_FAILED,
                    workflow_id,
                    data={"errors": result.errors[:5]},
                )
            )

        self.history.persist(workflow_id)
        self._display_report(result)
        return result

    def _run_sequential(
        self,
        recipe: Recipe,
        executor: RecipeExecutor,
        result: OrchestrationResult,
        workflow_id: str,
        wf_state: WorkflowState,
        progress_callback: Optional[Callable[..., None]],
    ) -> None:
        """Run steps sequentially."""
        for step in recipe.steps:
            self.history.append(
                ExecutionEvent.create(
                    EventKind.STEP_SCHEDULED, workflow_id, step.order
                )
            )
            wf_state.step_transition(step.order, StepStatus.STARTED)

            step_result = self._execute_and_verify_step(
                executor, step, workflow_id, wf_state
            )
            result.step_results.append(step_result)

            if step_result.verification.passed:
                result.completed_steps += 1
                wf_state.step_transition(step.order, StepStatus.COMPLETED)
                self.history.append(
                    ExecutionEvent.create(
                        EventKind.STEP_COMPLETED, workflow_id, step.order
                    )
                )
                self.console.print(f"[green]✓[/green] Step {step.order} passed")
            else:
                result.failed_steps += 1
                result.status = OrchestrationStatus.FAILED
                wf_state.step_transition(step.order, StepStatus.FAILED)
                self.history.append(
                    ExecutionEvent.create(
                        EventKind.STEP_FAILED,
                        workflow_id,
                        step.order,
                        data={"errors": step_result.verification.errors[:3]},
                    )
                )
                self.console.print(f"[red]✗[/red] Step {step.order} failed")
                for error in step_result.verification.errors:
                    result.errors.append(f"Step {step.order}: {error}")

            for warning in step_result.verification.warnings:
                result.warnings.append(f"Step {step.order}: {warning}")

            if progress_callback:
                progress_callback(step_result, result)

            if not step_result.verification.passed:
                if self.enable_rollback:
                    self.history.append(
                        ExecutionEvent.create(
                            EventKind.ROLLBACK_STARTED, workflow_id, step.order
                        )
                    )
                    self._handle_failure(result, step)
                    self.history.append(
                        ExecutionEvent.create(
                            EventKind.ROLLBACK_COMPLETED, workflow_id, step.order
                        )
                    )
                else:
                    result.status = OrchestrationStatus.PARTIAL
                break

    def _finalize_workflow(
        self,
        result: OrchestrationResult,
        workflow_id: str,
        wf_state: WorkflowState,
    ) -> None:
        if result.status == OrchestrationStatus.SUCCESS:
            wf_state.transition(WorkflowStatus.COMPLETED)
            self.history.append(
                ExecutionEvent.create(
                    EventKind.WORKFLOW_COMPLETED,
                    workflow_id,
                    data={"success_rate": result.success_rate},
                )
            )
        elif result.status == OrchestrationStatus.FAILED:
            wf_state.transition(WorkflowStatus.FAILED)
            self.history.append(
                ExecutionEvent.create(
                    EventKind.WORKFLOW_FAILED,
                    workflow_id,
                    data={"errors": result.errors[:5]},
                )
            )

    def _execute_and_verify_step(
        self,
        executor: RecipeExecutor,
        step: RecipeStep,
        workflow_id: str = "",
        wf_state: Optional[WorkflowState] = None,
    ) -> StepResult:
        """Execute single step and verify results, with optional LLM self-healing and constitutional review."""
        step_start = time.time()
        self_healed = False

        # Constitutional review before execution (EXECUTE hook)
        step_review = None
        if self.constitution:
            step_review = self._review_step_constitution(step, workflow_id)
            if step_review.blocked and self.constitutional_mode == "enforce":
                self.console.print(
                    f"[bold red]🚫 Step {step.order} blocked by Constitutional AI[/bold red]"
                )
                from ..verifier import ExecutionResult, VerificationReport
                blocked_result = ExecutionResult(
                    exit_code=1,
                    stderr=f"Constitutional violation: {step_review.summary}",
                )
                verification = VerificationReport(
                    passed=False,
                    errors=[
                        f"Constitutional AI: {r.reason}"
                        for r in step_review.principle_results
                        if not r.passed
                    ],
                )
                return StepResult(
                    step=step,
                    execution=blocked_result,
                    verification=verification,
                    self_healed=False,
                    constitutional_score=(
                        step_review.overall_score if step_review else None
                    ),
                    constitutional_review={
                        "overall_score": step_review.overall_score,
                        "blocked": step_review.blocked,
                        "principles": [
                            {
                                "principle": r.principle.value,
                                "score": r.score,
                                "passed": r.passed,
                            }
                            for r in step_review.principle_results
                        ],
                    }
                    if step_review
                    else None,
                )

        execution_result = executor.execute_step(step)

        step_type = step.params.get("type", "shell") if step.params else "shell"
        if (
            step_type == "shell"
            and execution_result.exit_code != 0
            and self.retry_policy.is_retryable(
                execution_result.stderr or "", execution_result.exit_code
            )
            and self.planner.llm_client
            and hasattr(self.planner.llm_client, "generate")
        ):
            execution_result, self_healed = self._self_heal_step(
                step, execution_result, workflow_id, executor
            )

        criteria = step.params.get("verification", {})
        verification_report = self.verifier.verify(execution_result, criteria)

        duration = time.time() - step_start
        self.telemetry.record_step(
            step_order=step.order,
            title=step.title,
            duration=duration,
            exit_code=execution_result.exit_code,
            self_healed=self_healed,
            agent=step.agent,
        )

        return StepResult(
            step=step,
            execution=execution_result,
            verification=verification_report,
            self_healed=self_healed,
            constitutional_score=step_review.overall_score if step_review else None,
            constitutional_review={
                "overall_score": step_review.overall_score,
                "blocked": step_review.blocked,
                "passed": step_review.passed,
                "principles": [
                    {
                        "principle": r.principle.value,
                        "score": r.score,
                        "passed": r.passed,
                        "reason": r.reason,
                    }
                    for r in step_review.principle_results
                ],
            }
            if step_review
            else None,
        )

    def _self_heal_step(
        self,
        step: RecipeStep,
        execution_result: Any,
        workflow_id: str,
        executor: RecipeExecutor,
    ) -> tuple:
        """Attempt LLM self-correction for a failed shell step. Returns (result, healed)."""
        command = step.description.strip()
        stderr = execution_result.stderr or ""
        self.console.print("[yellow]🔧 Attempting AI self-correction...[/yellow]")

        if workflow_id:
            self.history.append(
                ExecutionEvent.create(
                    EventKind.SELF_HEAL_ATTEMPTED,
                    workflow_id,
                    step.order,
                    data={"error": stderr[:200]},
                )
            )

        try:
            self.telemetry.record_llm_call()
            prompt = (
                f"This shell command failed: `{command}`. "
                f"Error: `{stderr[:500]}`. "
                "Suggest a corrected command. "
                "Reply with ONLY the corrected command, no explanation."
            )
            corrected = self.planner.llm_client.generate(prompt).strip()

            if corrected and corrected != command:
                from ..parser import RecipeStep as _RS

                healed_step = _RS(
                    order=step.order,
                    title=f"{step.title} (healed)",
                    description=corrected,
                    agent=step.agent,
                    params=step.params,
                )
                healed_result = executor.execute_step(healed_step)
                if healed_result.exit_code == 0:
                    self.console.print("[green]✓ Self-healing succeeded[/green]")
                    if workflow_id:
                        self.history.append(
                            ExecutionEvent.create(
                                EventKind.SELF_HEAL_SUCCEEDED,
                                workflow_id,
                                step.order,
                            )
                        )
                    return healed_result, True
                else:
                    self.telemetry.record_error(
                        f"Self-heal retry also failed for step {step.order}"
                    )
        except Exception as e:
            self.telemetry.record_error(f"Self-heal error: {e}")

        return execution_result, False

    # ------------------------------------------------------------------
    # Constitutional AI Hooks (PEV Integration)
    # ------------------------------------------------------------------

    def _review_plan_constitution(
        self, recipe: Recipe, goal: str
    ) -> ConReview:
        """
        Constitutional review of entire plan (PLAN hook).

        Args:
            recipe: The planned recipe
            goal: Original goal statement

        Returns:
            Constitutional review result
        """
        context = {
            "goal": goal,
            "recipe_name": recipe.name,
            "step_count": len(recipe.steps),
        }

        parameters = {
            "action_type": "plan",
            "steps": [
                {
                    "title": step.title,
                    "type": step.params.get("type", "shell") if step.params else "shell",
                    "agent": step.agent,
                }
                for step in recipe.steps
            ],
        }

        metadata = {
            "source": "orchestrator",
            "phase": "plan",
            "recipe": recipe.name,
        }

        return self.constitution.review(
            action="plan:review",
            context=context,
            parameters=parameters,
            metadata=metadata,
        )

    def _review_step_constitution(
        self, step: RecipeStep, workflow_id: str = ""
    ) -> ConReview:
        """
        Constitutional review of single step (EXECUTE hook).

        Args:
            step: The step to review
            workflow_id: Current workflow ID

        Returns:
            Constitutional review result
        """
        context = {
            "workflow_id": workflow_id,
            "step_order": step.order,
            "step_title": step.title,
        }

        parameters = {
            "command": step.description.strip(),
            "type": step.params.get("type", "shell") if step.params else "shell",
            "agent": step.agent,
            "verification": step.params.get("verification", {}),
        }

        metadata = {
            "source": "orchestrator",
            "phase": "execute",
            "step": step.order,
        }

        return self.constitution.review(
            action="step:execute",
            context=context,
            parameters=parameters,
            metadata=metadata,
        )

    def _record_constitutional_metric(
        self,
        phase: str,
        score: float,
        recipe_name: Optional[str] = None,
        step_order: Optional[int] = None,
    ) -> None:
        """Record constitutional score metric.

        Args:
            phase: "plan", "execute", or "verify"
            score: Constitutional score 0-1
            recipe_name: Recipe name (for plan phase)
            step_order: Step order (for execute phase)
        """
        if hasattr(self.telemetry, 'record_constitutional_score'):
            self.telemetry.record_constitutional_score(
                phase=phase,
                score=score,
                recipe=recipe_name,
                step=step_order,
            )
        else:
            # Fallback to generic metric
            self.logger.info(
                f"Constitutional score [{phase}]: {score:.3f}",
                extra={"phase": phase, "score": score, "recipe": recipe_name, "step": step_order},
            )

    # ------------------------------------------------------------------
    # Backward-compat display helpers (previously private methods)
    # ------------------------------------------------------------------

    def _display_report(self, result: OrchestrationResult) -> None:
        display_report(result, self.console)

    def _format_status(self, status: OrchestrationStatus) -> str:
        return format_status(status)

    def _handle_failure(
        self, result: OrchestrationResult, failed_step: RecipeStep
    ) -> None:
        handle_failure(result, failed_step, self.enable_rollback, self.console)


__all__ = ["RecipeOrchestrator"]
