# Code Review — Super Command #8: Harness Verifier Merge + DAG Scheduler Swap

> Reviewer: code-reviewer
> Scope: `src/core/runtime_adapter.py` (+161/-12), `tests/test_runtime_verify_merge.py` (14 tests), `tests/test_runtime_dag_order.py` (8 tests), `tests/test_runtime_multistep_cycle.py` (5 tests)
> Plan: `.orchestrate/latest/plan.md` (Architecture Gap #4)
> Baseline: `8dcb6f759` (SC7 shipped)

---

## Summary

The change delivers exactly what the plan describes: (1) `verify()` now delegates to `RecipeVerifier` via two adapter helpers, (2) `_run_goal` executes multi-step plans in topological order via Kahn's algorithm. The diff is tight, isolated to `runtime_adapter.py` + 3 new test files. No rewrite, no second orchestrator, no workflow touch. The 27 new tests pass; `ruff check` is clean.

Parity claim ("0 new failures vs baseline") is **credible**: the 256 full-suite failures (and the single `test_autonomous_loop` failure in the protected-flow subset) are all pre-existing on the stashed baseline, confirmed by re-running with changes reverted.

**Verdict: APPROVE with 1 medium + 3 low findings.** No critical or high issues. The implementation is correct, well-tested, and low-risk. The one medium finding is a latent robustness gap in `verify()` when `criteria_dict` is non-empty but the injected verifier has `strict_mode=False` — the fallback branch is silently skipped. The low findings are minor code-quality observations.

---

## Findings (ranked most-severe first)

### MEDIUM-1 — Empty-criteria fallback only triggers when `criteria.checks` is empty, but a non-empty `Criteria` that maps to an empty `criteria_dict` silently proceeds to the verifier with no checks

**File:line** — `src/core/runtime_adapter.py:857-874`

```python
def verify(self, observation: Observation, criteria: Criteria) -> Verification:
    criteria_dict = _criteria_to_verifier_dict(criteria)
    if not criteria_dict:
        # Empty criteria: preserve legacy behavior — passed iff no error.
        return Verification(passed=observation.result.error is None)
    ...
    report = self._verifier.verify(exec_result_like, criteria_dict)
```

If a caller passes `Criteria(checks=[CheckSpec(kind="unknown_kind", ...)])`, then `_criteria_to_verifier_dict` returns `{}` (unknown kinds are skipped per `_criteria_to_verifier_dict:222`), and `not criteria_dict` is True → the fallback returns `Verification(passed=True)` even though the caller explicitly asked for checks. This is the documented YAGNI behavior ("strict-YAGNI: only maps the kinds core currently emits"), so it is **intentional** and the plan explicitly calls it out (Step 1.1). However, it's worth noting: a future caller who adds a new `CheckSpec` kind without updating the adapter will silently get a "pass" verdict with zero checks, not a failure. The test `test_unknown_kind_skipped` locks this in.

**Recommendation:** Accept as-is per plan. If this bites in future, the fix is to log a warning (not just debug) when unknown kinds are skipped, or to raise. Document the invariant in the `verify()` docstring.

---

### LOW-1 — `_ExecResultLike` uses mutable default `metadata: dict` — classic dataclass footgun

**File:line** — `src/core/runtime_adapter.py:191-203`

```python
@dataclass
class _ExecResultLike:
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

The class uses `field(default_factory=dict)` correctly, so the mutable-default footgun is **not** present. No issue. (Confirmed — the `@dataclass` decorator + `default_factory` is the correct pattern.)

---

### LOW-2 — `test_repair_budget_exhausted_fails` comment is misleading

**File:line** — `tests/test_runtime_multistep_cycle.py:187-190`

```python
# The inner loop retries at most _MAX_REPAIR_ATTEMPTS times; the final
# verify failure exits the loop before execute() is called again, so the
# total dispatch count equals the cap (not cap+1).
assert dispatcher.calls == _MAX_REPAIR_ATTEMPTS
```

The comment explains why calls == 3 (not 4) correctly: `repair()` returns ESCALATE once `_repair_count >= 3`, breaking the loop before the 4th `execute()`. This is accurate. But the comment could be clearer by noting the dispatch count equals `_MAX_REPAIR_ATTEMPTS` only because `repair()` short-circuits on the cap — a subtle coupling between two independent counters (`attempts` in the loop vs `_repair_count` in `repair()`). No functional bug.

---

### LOW-3 — `_topological_task_order` uses `queue.pop(0)` — O(n^2) for wide graphs

**File:line** — `src/core/runtime_adapter.py:174`

```python
while queue:
    current = queue.pop(0)
```

`list.pop(0)` is O(n). For the current 7-task GoalEngine plan this is irrelevant. If the planner ever emits 50+ tasks with wide fan-out, this becomes measurable. Not a production risk today.

**Recommendation:** Replace with `collections.deque` if task counts grow beyond ~20.

---

## Checklist Verification

### 1. Root cause actually addressed?

**YES.** `verify()` (`runtime_adapter.py:857`) builds a criteria-dict via `_criteria_to_verifier_dict`, constructs `_ExecResultLike`, calls `self._verifier.verify()`, and maps back via `_report_to_verification`. The wiring test (`test_verify_calls_injected_verifier`) proves delegation with a mock. `_run_goal` (`runtime_adapter.py:512`) calls `_topological_task_order(tasks)` when `_plan_has_dependencies(p)`. Both root causes (divergent verifier, dependency-blind loop) are closed.

### 2. No broken business logic in blast radius.

**VERIFIED.**
- `mekong run` for unknown agents: `plan()` returns a single-step plan with no dependencies → `_plan_has_dependencies` is False → fast path → `ordered = tasks` → sequential iteration preserved exactly (`runtime_adapter.py:579-581, 512`).
- `cook` / `goal` / `implement`: multi-step plans go through the topological path, but the inner `_run_task_loop` (execute→observe→verify→repair) is unchanged. Only the outer ordering changes.
- Protected flows (Buzz webhook via `run_from_payload`): single-step payloads take the fast path; multi-step is new capability only for registered built-in agents.

### 3. No new failure modes.

**VERIFIED.**
- **Circular deps:** `_topological_task_order` raises `RuntimeError("circular task dependency detected among: ...")` when `len(ordinal_ids) != len(tasks)` (`runtime_adapter.py:182-186`). Tested by `test_cyclic_dependency_raises`.
- **Duplicate step ids:** Detected at `runtime_adapter.py:151-152` → `RuntimeError("duplicate task step ids in plan")`.
- **Unknown dep targets:** Detected at `runtime_adapter.py:162-165` → `RuntimeError("task 'X' depends on unknown step 'Y'")`.
- **Empty criteria fallback:** `if not criteria_dict: return Verification(passed=...)` preserves legacy behavior. Tested by `test_verify_empty_criteria_falls_back`.
- **Result→ExecutionResult mapping:** `_ExecResultLike` maps `error=None→exit_code=0`, `error="x"→exit_code=1, stderr="x"`, `output→stdout=str(output)`. Matches `RecipeVerifier.verify_output_contains` which reads `stdout + "\n" + stderr`.

### 4. Follows existing patterns.

**YES.** Compared against:
- `src/core/verifier.py` — `RecipeVerifier.verify()` is consumed as-is (no modification). The adapter pattern (`_criteria_to_verifier_dict` + `_report_to_verification`) mirrors how the codebase translates between layers elsewhere.
- `src/core/dag_scheduler.py` — the plan correctly identifies that `DAGScheduler` keys by integer `order` while `Step.dependencies` is `list[str]`, so reusing it would cause silent mismatches. The new `_topological_task_order` implements Kahn's algorithm on string ids, matching `TaskGraph.ready_tasks()` semantics without importing GoalEngine models into core.
- `tests/test_core_lifecycle_contract.py` — the existing lifecycle tests still pass (1 failed, 37 passed in the protected-flow subset; the 1 failure is pre-existing on baseline).

### 5. Tests are real, not mocks-to-pass.

**YES.** The tests exercise real behavior:
- `TestVerifyExitCode` and `TestVerifyOutputPattern` call `rt.verify()` with real `RecipeVerifier` (injected by default).
- `test_execute_verify_repair_cycle` proves the full execute→verify→fail→repair→re-verify→pass cycle with a stateful dispatcher that returns different outputs on each call.
- `test_repair_budget_exhausted_fails` proves the repair cap exits with all-failed verdicts and correct dispatch count.
- `test_goal_runs_in_topological_order` is a true integration test: it patches `plan`/`delegate` but uses real `_run_task_loop` and real `_topological_task_order`.
- The mock-verifier tests (`TestVerifyUsesRecipeVerifier`) prove wiring without reimplementation — the mock is the assertion target, not a bypass.

The only test that uses a recording-wrapper pattern (`recording_run_task_loop`) delegates to the real `original_run_task_loop` inside, so it exercises the full inner loop.

### 6. Absolute rules compliance.

- **No rewrite:** YES — `RecipeVerifier` and `DAGScheduler` are untouched. Only `runtime_adapter.py` is modified.
- **No second orchestrator:** YES — the new helper `_topological_task_order` is a pure function, not a framework.
- **No `.github/workflows/*` touch:** Confirmed via `git status` — clean on that path.
- **No marketplace/tokenomics/custody:** N/A — the change is in core runtime verification + ordering.

### 7. Parity claim (0 new failures vs baseline) credible?

**YES — verified empirically.** Stashed SC8 changes and re-ran the full suite: identical 256 failures on baseline. The 49 failures in `test_nl_routing.py`/`test_plugin_loading.py`/`test_rbac.py`/`test_self_healing.py`/`test_smart_router.py` are identical with and without SC8 changes (tested both ways). The `test_autonomous_loop::test_full_loop_returns_result` failure is pre-existing on baseline. SC8 introduces **0** new failures.

---

## Plan TODO Status

| Phase | Status | Evidence |
|---|---|---|
| Phase 1 — Verifier merge | **Complete** | `_criteria_to_verifier_dict`, `_report_to_verification`, `_ExecResultLike`, `verify()` rewrite all in place. 14 tests pass. |
| Phase 2 — DAG order | **Complete** | `_topological_task_order`, `_plan_has_dependencies`, `_run_goal` edit all in place. 8 tests pass. |
| Phase 3 — E2E + parity | **Complete** | `test_runtime_multistep_cycle.py` (5 tests) covers multistep cycle, repair, single-step parity. Parity verified. |
| Phase 4 — Quality gates | **Complete** | `ruff check` clean. Docs updated (`docs/architecture.md`, `docs/development-roadmap.md`, `docs/project-changelog.md` per `git status`). |

---

## Recommended Actions

1. **(Optional) MEDIUM-1:** Add a `logger.warning` when `_criteria_to_verifier_dict` drops unknown kinds, so future additions get a signal. Not blocking.
2. **(Optional) LOW-3:** Swap `list.pop(0)` for `collections.deque` if planner grows beyond ~20 tasks. Not blocking.
3. Merge as-is — the change is correct, well-isolated, and low-risk.

---

## Metrics

- New tests: 27 (14 + 8 + 5), all passing
- `ruff check` on changed files: 0 errors
- Full-suite parity: 0 new failures (256 pre-existing, unchanged)
- LOC changed: +161/-12 (net +149)
- New test files: 3
- Blast radius: 1 production file (`src/core/runtime_adapter.py`)
