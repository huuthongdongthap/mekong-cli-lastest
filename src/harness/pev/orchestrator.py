# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""PEV Orchestrator -- goal to plan to exec to verify to memory loop.

Wires existing PEV components into a single end-to-end pipeline.
Pure sequential glue: no async, no threading, no retries beyond what the
executor already handles.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from src.core.memory_bridge import MemoryBridge, MemoryKind, MemoryRecord, get_bridge
from src.harness.pev.executor import RecipeExecutor
from src.harness.pev.metrics_collector import get_pev_metrics
from src.harness.pev.parser import Recipe, RecipeParser
from src.core.planner import PlanningContext, RecipePlanner
from src.core.verifier import RecipeVerifier, VerificationReport


# B5: NLU integration — intent detection with B3 core
def _detect_recipe_intent(recipe: "Recipe") -> str:
    """Detect intent for a parsed recipe using B3 unified NLU.

    Delegates to ``RecipeParser.detect_intent`` which imports from
    ``src.core.nlu`` (the B3 unified classifier). Falls back to empty
    string on any error so the caller never crashes.
    """
    try:
        return RecipeParser.detect_intent(recipe)
    except Exception:
        return ""


class PipelineResult:
    """Outcome of a full PEV pipeline run."""

    def __init__(
        self,
        *,
        success: bool,
        pipeline_id: str,
        goal: str,
        steps_total: int,
        steps_passed: int,
        steps_failed: int,
        duration_ms: float,
        error: str | None,
        recipe: Recipe,
        verification_report: VerificationReport | None,
    ) -> None:
        self.success = success
        self.pipeline_id = pipeline_id
        self.goal = goal
        self.steps_total = steps_total
        self.steps_passed = steps_passed
        self.steps_failed = steps_failed
        self.duration_ms = duration_ms
        self.error = error
        self.recipe = recipe
        self.verification_report = verification_report


class PEVOrchestrator:
    """Coordinates the full Plan-Execute-Verify pipeline.

    Accepts either a recipe file path (.md) or a plain goal string.
    When given a goal string, ``RecipePlanner`` decomposes it into a
    ``Recipe`` before execution.
    """

    def __init__(self, memory: MemoryBridge | None = None) -> None:
        """Initialize the orchestrator.

        Args:
            memory: Optional ``MemoryBridge`` instance. Falls back to
                ``get_bridge()`` at run time when omitted.
        """
        self.memory = memory
        self._parser = RecipeParser()
        self._planner = RecipePlanner()

    def run(self, recipe_or_goal: str | Path) -> PipelineResult:
        """Run a full PEV pipeline.

        Args:
            recipe_or_goal: Path to a Markdown recipe file or a plain
                goal string to decompose via ``RecipePlanner``.

        Returns:
            ``PipelineResult`` capturing execution outcome and metadata.
        """
        pipeline_id = uuid.uuid4().hex[:8]
        t0 = time.perf_counter()

        error: str | None = None
        goal = ""
        recipe: Recipe | None = None

        try:
            recipe = self._resolve_recipe(recipe_or_goal)
            goal = (recipe.title or recipe.name or str(recipe_or_goal)).strip()

            executor = RecipeExecutor(recipe)
            verifier = RecipeVerifier(strict_mode=True)

            metrics = get_pev_metrics()
            metrics.record_pipeline_start(pipeline_id)

            passed = 0
            failed = 0

            for step in recipe.steps:
                step_t0 = time.perf_counter()
                result = executor.execute_step(step)
                duration_ms = (time.perf_counter() - step_t0) * 1000

                metrics.record_step_result(
                    pipeline_id,
                    step.order,
                    success=result.exit_code == 0,
                    duration_ms=duration_ms,
                )

                criteria = (step.params or {}).get("verification", {})
                if criteria:
                    step_report = verifier.verify(result, criteria)
                    if step_report.passed:
                        passed += 1
                    else:
                        failed += 1
                else:
                    if result.exit_code == 0:
                        passed += 1
                    else:
                        failed += 1

            status = "completed" if failed == 0 else "failed"
            metrics.record_pipeline_end(pipeline_id, status)

        except Exception as exc:
            error = str(exc)
            passed = 0
            failed = 0

        duration_ms = (time.perf_counter() - t0) * 1000
        steps_total = len(recipe.steps) if recipe else 0

        verification_report: VerificationReport | None = None
        if recipe is not None:
            try:
                verification_report = self._build_summary_report(
                    recipe, passed, failed
                )
            except Exception:
                pass

        memory_bridge = self.memory or get_bridge()
        try:
            memory_bridge.record(
                MemoryRecord(
                    content=(
                        f"Pipeline {pipeline_id}: goal={goal!r}, "
                        f"result={'OK' if error is None and failed == 0 else 'FAIL'}, "
                        f"steps={passed}/{steps_total} passed, "
                        f"duration_ms={duration_ms:.1f}"
                    ),
                    kind=MemoryKind.EPISODIC,
                    metadata={
                        "pipeline_id": pipeline_id,
                        "goal": goal,
                        "steps_total": steps_total,
                        "steps_passed": passed,
                        "steps_failed": failed,
                        "duration_ms": duration_ms,
                        "error": error,
                    },
                )
            )
        except Exception:
            pass

        success = error is None and failed == 0 and recipe is not None

        return PipelineResult(
            success=success,
            pipeline_id=pipeline_id,
            goal=goal,
            steps_total=steps_total,
            steps_passed=passed,
            steps_failed=failed,
            duration_ms=duration_ms,
            error=error,
            recipe=(
                recipe
                if recipe is not None
                else Recipe(name=str(recipe_or_goal), title=str(recipe_or_goal))
            ),
            verification_report=verification_report,
        )

    def _resolve_recipe(self, recipe_or_goal: str | Path) -> Recipe:
        """Return a ``Recipe`` from a file path or decompose a goal string."""
        if isinstance(recipe_or_goal, Path) or (
            isinstance(recipe_or_goal, str)
            and (
                recipe_or_goal.endswith(".md") or Path(recipe_or_goal).suffix == ".md"
            )
            and Path(recipe_or_goal).exists()
        ):
            path = Path(recipe_or_goal)
            parsed = self._parser.parse(path)
            if not parsed.title:
                parsed.title = path.stem
            # B5: detect intent after parse (delegates to B3 NLU)
            parsed.intent = _detect_recipe_intent(parsed)
            return parsed

        goal = str(recipe_or_goal)
        context = PlanningContext(goal=goal)
        return self._planner.plan(goal, context)

    def _build_summary_report(
        self, recipe: Recipe, passed: int, failed: int
    ) -> VerificationReport:
        """Build a top-level VerificationReport summarising whole-pipeline status."""
        from src.core.verifier import (
            VerificationCheck,
            VerificationStatus,
        )

        report = VerificationReport(
            passed=(failed == 0),
            checks=[
                VerificationCheck(
                    name="pipeline_summary",
                    status=(
                        VerificationStatus.PASSED
                        if failed == 0
                        else VerificationStatus.FAILED
                    ),
                    message=(
                        f"{passed}/{len(recipe.steps)} steps passed, "
                        f"{failed} failed"
                    ),
                    expected=len(recipe.steps),
                    actual=passed,
                )
            ],
            warnings=[],
            errors=[],
        )

        if failed > 0:
            report.errors.append(f"{failed} step(s) failed")

        return report
