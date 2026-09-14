# Plan — Architecture Gap #4: Harness Verifier Merge + DAG Scheduler Swap

> **TL;DR:** Core runtime `MekongCoreRuntimeImpl.verify()` uses a thin custom checker while the rich `RecipeVerifier` (exit_code / file / output / command checks) lives unused inside the core loop; and `_run_goal` iterates multi-step plans sequentially, ignoring the `depends_on` DAG that `GoalEngineAdapter` already embeds in `Step.dependencies`. Fix: (1) make `verify()` delegate to `RecipeVerifier` via a thin adapter that translates `Criteria`→criteria-dict and `VerificationReport`→`Verification`; (2) compute a real topological order from `Step.dependencies` in `_run_goal` and iterate tasks in that order (reusing the existing `TaskGraph.ready_tasks()` semantics, NOT the stub `harness/pev/dag_scheduler.py`); (3) keep the single-task `execute→observe→verify→repair` cycle intact as the inner loop. No second orchestration framework, no rewrite.

Execution: `.orchestrate/latest/execution.md`
Repo: `/Users/macbook/mekong-cli/.claude/worktrees/super-command-2` @ `8dcb6f759` (SC7 shipped)

---

## 1. Reframed problem

### What the gap actually is

The repo has **three** verification/DAG surfaces that don't talk to each other:

| Surface | Location | State |
|---|---|---|
| Core runtime verify | `src/core/runtime_adapter.py:716` `verify()` | Thin: only `exit_code` + `output_pattern` via `_evaluate_check` |
| Harness/Orchestrator verifier | `src/core/verifier.py:74` `RecipeVerifier` + `VerificationReport` | Rich: `verify_exit_code`, `verify_file_exists`, `verify_file_not_exists`, `verify_output_contains`, `verify_output_not_contains`, `verify_custom_check` — used by `PEVOrchestrator` and `RecipeOrchestrator`, **NOT** by `MekongCoreRuntimeImpl`. NOTE: there is NO `command_succeeds` method (corrected per plan gate Finding 1). |
| Core DAG scheduler | `src/core/dag_scheduler.py:34` `DAGScheduler` | Real topological sort + ThreadPoolExecutor — used by `src/core/orchestrator/runner.py`, **NOT** by core runtime |
| Harness DAG scheduler | `src/harness/pev/dag_scheduler.py:11` | **STUB** — returns `range(len(steps))` |
| GoalEngine task graph | `src/mekongcli/core/goal_engine/models.py:112` `TaskGraph.ready_tasks()` | Computes ready tasks from `depends_on` — used internally by GoalEngine service, **NOT** consumed by core runtime |

The core runtime (`_run_goal`, line 365) loops `for task in tasks: _run_task_loop(task, ...)` — **sequential, dependency-blind**. But `GoalEngineAdapter._task_to_step` (line 162) already copies `task.depends_on` into `Step.dependencies`. The data is there; the loop ignores it.

### Why it matters

- Multi-step plans from GoalEngine (7 role-aware tasks with `depends_on` edges) execute in arbitrary order. A `reviewer` task that depends on `qa+security+docs` can run before them — meaningless verification.
- Core runtime verification is weaker than the harness standard. A goal that passes core `verify()` can fail the richer `RecipeVerifier` checks (file existence, command success) that the rest of the repo uses — two divergent quality bars.
- The stub `harness/pev/dag_scheduler.py` is dead code; the real `DAGScheduler` already exists in core. Closing the gap means **one** verifier, **one** DAG order, both flowing through the core runtime.

### What we are NOT doing

- NOT rewriting `RecipeVerifier` or `DAGScheduler` — both are mature and tested.
- NOT removing `PEVOrchestrator` or `RecipeOrchestrator` — they keep using `RecipeVerifier` directly; the change is that core runtime now shares the same verifier.
- NOT touching `src/harness/pev/dag_scheduler.py` stub unless tests require it (it's isolated; `PEVOrchestrator` does not import it — confirmed, orchestrator imports from `src.core.verifier`, not the stub).
- NOT making execution concurrent — `_run_task_loop` stays single-threaded; we only reorder the outer loop topologically. (Concurrency is a future gap, not this one.)
- NOT touching `.github/workflows/*` (owned by concurrent PR #7).

---

## 2. Work checklist

### Phase 1 — Harness verifier merge into core runtime `verify()`

**Goal:** `MekongCoreRuntimeImpl.verify()` produces the same verdict as `RecipeVerifier` for equivalent criteria, while keeping the core `Verification` return type so `_run_task_loop` is untouched.

**Step 1.1 — Add adapter helper to translate core Criteria ↔ RecipeVerifier criteria-dict.**

File: `src/core/runtime_adapter.py` (add a module-level helper, ~25 LOC).

- Add `_criteria_to_verifier_dict(criteria: Criteria) -> dict` that maps:
  - `CheckSpec(kind="exit_code", params={"expected": 0})` → `{"exit_code": {"expected": N}}`
  - `CheckSpec(kind="output_pattern", params={"pattern": "..."})` → `{"output_contains": {"pattern": "..."}}`
  - Unknown kinds → skipped (logged at debug). This keeps the adapter strict-YAGNI: only maps the kinds core currently emits. **NOTE:** `RecipeVerifier` does NOT have a `command_succeeds` method. The actual methods are: `verify_exit_code`, `verify_file_exists`, `verify_file_not_exists`, `verify_output_contains`, `verify_output_not_contains`, `verify_custom_check`. The adapter only maps criteria to the verifier methods that exist.
- Add `_report_to_verification(report: "VerificationReport") -> Verification` that maps:
  - `report.passed` and any FAILED/WARNING check → `VerificationCheck(check=CheckSpec(kind=check.name), passed=(status==PASSED), detail=check.message)`
  - `report.errors` → `Verification.failures`

**Step 1.2 — Inject `RecipeVerifier` into `MekongCoreRuntimeImpl` and call it from `verify()`.**

File: `src/core/runtime_adapter.py`.

- In `__init__`, add optional `verifier: RecipeVerifier | None = None` param; default `self._verifier = verifier or RecipeVerifier(strict_mode=True)`. (Import inside `__init__` to avoid circular import — `verifier.py` imports nothing from runtime_adapter.)
- Rewrite `verify()` (line 716) to:
  1. Build `criteria_dict = _criteria_to_verifier_dict(criteria)`.
  2. Build a minimal `ExecutionResult`-shaped object from `Observation` (needs `.exit_code`, `.stdout`, `.stderr`, `.metadata`). **Key detail:** core `Observation.result` is a `Result` (has `.output`, `.error`, `.metadata`), NOT an `ExecutionResult`. So build an adapter dataclass `_ExecResultLike(exit_code: int, stdout: str, stderr: str, metadata: dict)` with this explicit mapping:
    - `exit_code = 0 if result.error is None else 1`
    - `stdout = str(result.output)` — `verify_output_contains` reads `result.stdout + "\n" + result.stderr` (verifier.py:193), so output goes to stdout.
    - `stderr = result.error or ""` — error content routed to stderr so `verify_output_not_contains` can detect it.
    - `metadata = result.metadata or {}` — preserved for `verify_custom_check` consumers.
    This mirrors how `RecipeExecutor` sets exit codes and matches `ExecutionResult` field semantics (verifier.py:32-40).
  3. Call `self._verifier.verify(exec_result_like, criteria_dict) -> VerificationReport`.
  4. Return `_report_to_verification(report)`.
- Keep `_evaluate_check` as a **fallback** only if `criteria_dict` is empty (no criteria): then `verify()` returns `Verification(passed=(result.error is None))`. This preserves the current no-criteria behavior so existing tests with `_DEFAULT_CRITERIA` (which has one `exit_code` check) still pass.

**Step 1.3 — Tests for Phase 1.**

File: `tests/test_runtime_verify_merge.py` (new).

- `test_verify_exit_code_pass`: criteria `exit_code expected=0`, observation with no error → `Verification.passed=True`, one check named `exit_code` PASSED.
- `test_verify_exit_code_fail`: observation with `error="boom"` → `passed=False`, failure mentions exit_code.
- `test_verify_output_pattern`: criteria `output_pattern pattern="OK"`, observation output `"OK done"` → passed; output `"no"` → failed.
- `test_verify_empty_criteria_falls_back`: empty Criteria → passed iff no error (parity with old behavior).
- `test_verify_uses_recipe_verifier`: assert `mock_verifier.verify` was called with an object whose `exit_code` matches — proves wiring, not reimplementation.
- `test_verify_report_errors_surface`: a `VerificationReport` with `errors=["x"]` → `Verification.failures == ["x"]`.

**Acceptance:** `tests/test_runtime_verify_merge.py` all pass; existing `test_core_lifecycle_contract.py`, `test_runtime_delegate.py`, `test_runtime_safety.py`, `test_autonomous_loop.py` unchanged and green.

---

### Phase 2 — DAG-aware task ordering in `_run_goal`

**Goal:** Multi-step plans (steps with `dependencies`) execute in topological order; single-step plans unchanged.

**Step 2.1 — Add topological-order helper operating on `list[Task]`.**

File: `src/core/runtime_adapter.py` (add module-level, ~30 LOC).

- Add `def _topological_task_order(tasks: list[Task]) -> list[Task]`:
  - Build `id→task` map. For each task, `deps = task.step.dependencies` (list of step ids — **string IDs** like `"task-abc123"`, from `GoalEngineAdapter._task_to_step` at `adapters/goal_engine_adapter.py:162-173`).
  - Kahn's algorithm: compute in-degree from deps; seed queue with zero-in-degree tasks; emit in order; decrement dependents. Detect cycles — on cycle, **fail loud** by raising `RuntimeError("circular task dependency: ...")` rather than silently ordering. (Cycles indicate a GoalEngine planner bug; masking them is worse.)
  - **This does NOT reuse `DAGScheduler`** (`src/core/dag_scheduler.py:34`). `DAGScheduler` keys by `order` (int) and compares `dependencies` against completed order indices — but `Step.dependencies` is `list[str]` (string IDs, per `protocols.py:140`). Reusing `DAGScheduler` would cause silent type-mismatch failures (string vs int comparison never matches). Instead, this helper implements a **string-ID-keyed** topological sort directly on `task.step.dependencies`, matching the same algorithm as `TaskGraph.ready_tasks()` (models.py:112) but operating on core `Task` objects — no import of GoalEngine models into core runtime (keeps core small, no new dependency).
  - **Degenerate case:** single-step plans or plans with all `dependencies=[]` → topological sort returns tasks in original order (sequential parity preserved).

**Step 2.2 — Use the order in `_run_goal`.**

File: `src/core/runtime_adapter.py`, `_run_goal` (line 365).

Replace:
```python
results: list[Result] = []
for task in tasks:
    results.append(self._run_task_loop(task, goal.criteria))
```
With:
```python
results: list[Result] = []
ordered = _topological_task_order(tasks) if _plan_has_dependencies(plan) else tasks
for task in ordered:
    results.append(self._run_task_loop(task, goal.criteria))
```
Where `_plan_has_dependencies(plan)` returns `any(s.dependencies for s in plan.steps)` — fast path skips the algorithm for single-step plans (the common `mekong run` path), preserving current behavior exactly.

**Step 2.3 — Tests for Phase 2.**

File: `tests/test_runtime_dag_order.py` (new).

- `test_single_step_unaffected`: plan with 1 step, no deps → order is identity; `_run_task_loop` called once.
- `test_linear_chain_order`: 3 tasks A→B→C (B depends on A, C on B) → execution order is [A, B, C]. Assert via mock on `_run_task_loop` call args.
- `test_diamond_order`: architect → [backend, infra] → reviewer. Valid topsort: architect first, reviewer last, backend/infra in middle (order between them non-deterministic — assert set equality for the middle). This mirrors the real GoalEngine 7-task graph shape.
- `test_cycle_raises`: A depends on B, B depends on A → `RuntimeError` with "circular".
- `test_no_deps_uses_fast_path`: 3 tasks, none with dependencies → `_plan_has_dependencies` False → `_topological_task_order` NOT called (assert via mock patch).
- `test_merged_result_aggregates_all`: verify `_merge_results` still receives all results in execution order.

**Acceptance:** `tests/test_runtime_dag_order.py` pass; existing lifecycle/delegate tests green.

---

### Phase 3 — Wire DAG order + verifier together through `run()` and `run_from_payload()`

**Goal:** End-to-end, a multi-step goal flows `plan() → delegate() → topological execute→verify→repair per task → observe → remember → commit`. No behavior change for single-step goals.

**Step 3.1 — E2E test proving the full multi-step cycle.**

File: `tests/test_runtime_multistep_cycle.py` (new).

- Build a `MekongCoreRuntimeImpl` with a real `GoalEngineAdapter` (in-memory `SQLiteGoalStore`) and a mock dispatcher that returns success for every task.
- Call `run("implement a hello-world CLI")` (registered `cto` agent → multi-step plan).
- Assert:
  - `plan()` returned a Plan with 7 steps and non-empty `dependencies` on steps 2–7.
  - `delegate()` returned 7 tasks.
  - `_run_task_loop` was called 7 times, in an order that respects `dependencies` (architect first, reviewer last).
  - Final `Result.error is None` (all passed verify).
  - `remember()` was called (memory write path intact).
- Second test: make the dispatcher fail the `backend` task → assert downstream tasks (qa/security/docs/reviewer, which depend on backend) still execute (they verify and may fail), but the final merged result carries the error. This proves the DAG does NOT short-circuit on failure (current behavior preserved — `_run_task_loop` handles per-task repair, not graph cancellation).

**Step 3.2 — Parity sweep.**

Run full test suite, compare against baseline `.orchestrate/latest/baseline_d71e13fa02.txt`. New failures = 0.

**Acceptance:** E2E test passes; parity gate EMPTY for new failures.

---

### Phase 4 — Quality gates + cleanup

- `python3 -m ruff check src/core/runtime_adapter.py tests/test_runtime_verify_merge.py tests/test_runtime_dag_order.py tests/test_runtime_multistep_cycle.py` → clean.
- `python3 -m mypy src/core/runtime_adapter.py` (or pyright) → 0 new errors.
- `python3 -m pytest tests/ -q` → all green.
- Update `docs/architecture.md` §runtime: note that core runtime now shares `RecipeVerifier` and executes multi-step plans in topological order. (Delegate to docs-manager if available; otherwise a -line inline edit is fine.)
- Update `docs/development-roadmap.md` and `docs/project-changelog.md`: gap #4 closed.

---

## 3. Risks & gates

| Risk | Mitigation |
|---|---|
| `ExecutionResult` shape mismatch — core `Result` lacks `exit_code` | Build `_ExecResultLike` adapter in Step 1.2; `exit_code = 0 if error is None else 1` mirrors `RecipeExecutor` convention. Test explicitly. |
| `_evaluate_check` fallback regression | Keep fallback for empty criteria; test `test_verify_empty_criteria_falls_back` locks parity. |
| Topological sort changes execution order for existing multi-step users | Only triggers when `Step.dependencies` is non-empty. Single-step (`mekong run` for unknown agents) takes the fast path — zero behavior change. |
| Cycle in GoalEngine planner output hangs or silently mis-orders | Kahn's algorithm raises `RuntimeError` on cycle (fail loud). Add to changelog as a planner-quality signal. |
| `RecipeVerifier` import creates circular dependency | `src/core/verifier.py` imports only stdlib + `src.core.executor` (ExecutionResult). No import of runtime_adapter. Verified — safe to import inside `__init__`. |
| `_run_task_loop` repair count (`_repair_count`) is per-mission, not per-task | This is pre-existing behavior; we do NOT change it. Document as a known limitation in the plan notes. (Per-task repair budget is a future gap.) |
| Protected flows (NOWPayments IPN, license gate, payment) | These flow through `run_from_payload` → `_run_goal`. Single-step payloads take the fast path (no deps) → zero change. Verified by `test_buzz_transport.py` + `test_phase6_license_validation.py` staying green. |
| `.github/workflows/*` | NOT touched (PR #7 owns them). |

**Gates (must pass before merge):**
1. `ruff check` clean on changed files.
2. `mypy`/`pyright` 0 new errors on changed files.
3. `pytest tests/ -q` all green, parity vs baseline: 0 new failures.
4. New tests in §2 all pass.
5. `mekong run`, `mekong cook`, `mekong goal`, `mekong implement` smoke-tested manually (see Ship plan).

---

## 4. Agent assignments

| Phase | Agent | Why |
|---|---|---|
| Phase 1 (verifier merge) | **fullstack-developer** | Precise adapter wiring between two existing modules; needs to read both `verifier.py` and `runtime_adapter.py` carefully. |
| Phase 2 (DAG order) | **fullstand-developer** (sequential after Phase 1 — same file `runtime_adapter.py`, avoid write conflict) | Kahn's algorithm + `_run_goal` edit; depends on Phase 1's `_topological_task_order` being in place. |
| Phase 3 (E2E + parity) | **tester** | Builds the multistep cycle test and runs the parity sweep. |
| Phase 4 (docs) | **docs-manager** | Architecture/roadmap/changelog updates. |
| Final review | **code-reviewer** | Whole diff review before commit. |

Note: Phases 1 and 2 both touch `src/core/runtime_adapter.py` — run them **sequentially** (not parallel) to avoid file conflict. Phase 3's unit-test files are independent and could be drafted in parallel, but the E2E test needs both phases merged, so Phase 3 runs after Phase 2.

---

## 5. Ship plan

### Pre-deploy checklist (run before any commit)
- [ ] `python3 -m ruff check src/ tests/` → 0 errors
- [ ] `python3 -m pytest tests/ -q` → all green (establish baseline if `baseline_d71e13fa02.txt` is stale)
- [ ] `python3 -m mypy src/core/runtime_adapter.py` → 0 new errors
- [ ] Confirm `.github/workflows/*` untouched (`git status` clean on that path)

### Commit
- Single conventional-commit: `feat(core): merge RecipeVerifier into runtime verify() and order multi-step plans topologically (gap #4)`
- Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
- Files: `src/core/runtime_adapter.py`, `tests/test_runtime_verify_merge.py`, `tests/test_runtime_dag_order.py`, `tests/test_runtime_multistep_cycle.py`, `docs/architecture.md`, `docs/development-roadmap.md`, `docs/project-changelog.md`

### PR
- Title: `feat(core): gap #4 — harness verifier merge + DAG scheduler swap`
- Body: summarize the three surfaces collapsed into one, link this plan, list gates.
- Target: `main`.

### CI verify
- GitHub Actions green (lint + test). Do NOT merge on red.

### Merge
- Squash or merge commit per repo convention.

### Deploy
- No separate deploy step for this change (library/CLI code; deploy happens via the regular release track, not this PR).

### Prod smoke (after merge)
- `mekong run "analyze Q3 revenue"` → single-step path, completes, no error.
- `mekong cook "build a todo API"` → multi-step (`cto`), 7 tasks execute, reviewer runs last.
- `mekong goal "ship tax module"` → goal persisted, task graph resumable.
- `mekong implement "add logging"` → multi-step, verify passes each task.

### Feature smoke
- Inspect mission tracer output (if attached): stages `goal → plan → delegate → execute → observe → remember → commit → finish` present, and per-task `log_step` records appear in topological order.

### Rollback readiness
- If parity gate shows new failures post-merge: revert the single commit (`git revert <sha>`), re-run parity, re-open gap. The change is isolated to `runtime_adapter.py` + 3 new test files — revert is clean, no migration, no schema.

### Ops / journal
- On ship: append to `docs/project-changelog.md` — `## v6.x — Gap #4 closed: core runtime shares RecipeVerifier + topological multi-step execution`.
- If cycle-raise fires in prod (should not, unless GoalEngine planner regresses): journal the incident with the cycle details — it's a planner bug surfacing, not a runtime bug.

---

## 6. Assumptions (confidence, what would change the answer)

- **HIGH:** `src/core/verifier.py:RecipeVerifier.verify()` accepts a criteria-dict with keys `exit_code`, `output_contains`, `output_not_contains`, `file_exists`, `file_not_exists`, `custom_check`. **NO `command_succeeds` key** — that method does not exist. Confirmed by reading `verify()` (line 281) and the individual `verify_*` methods (lines 89-460).
- **HIGH:** `GoalEngineAdapter._task_to_step` copies `depends_on` into `Step.dependencies` (verified line 162–173). So `_run_goal` can read the DAG without touching GoalEngine internals.
- **HIGH:** `src/harness/pev/dag_scheduler.py` stub is NOT imported by `PEVOrchestrator` (orchestrator imports `src.core.verifier`, not the stub). So leaving the stub untouched is safe. If any test imports it, that test is testing the stub itself and is out of scope.
- **MEDIUM:** `ExecutionResult` (used by `RecipeVerifier`, verifier.py:32-40) has fields `exit_code: int`, `stdout: str`, `stderr: str`, `output_files: list`, `metadata: dict`, `error: str | None`. The `_ExecResultLike` adapter provides `exit_code`, `stdout`, `stderr`, `metadata` (Step 1.2). `verify_output_contains` reads `result.stdout + "\n" + result.stderr` (verifier.py:193), so the stdout/stderr split matters. Verified during Phase 1.1.
- **MEDIUM:** `_repair_count` is per-mission (reset only in `start_mission`). With 7 tasks each potentially retrying 3×, the cap (3) will trip early. This is **pre-existing** behavior, not introduced by this change. Flag as a follow-up (per-task repair budget) but do NOT fix here — out of scope.
- **LOW:** `mekong run` for unknown agents produces a single-step plan (line 438–440) with no dependencies → fast path → zero behavior change. Verified by reading `plan()`.

---

## 7. File/function quick-reference (for subagent handoff)

| File | Function/line | Change |
|---|---|---|
| `src/core/runtime_adapter.py` | `__init__` (line 167) | Add `verifier: RecipeVerifier | None = None` param + `self._verifier` |
| `src/core/runtime_adapter.py` | `verify()` (line 716) | Rewrite to delegate to `self._verifier.verify()` via `_criteria_to_verifier_dict` + `_report_to_verification` |
| `src/core/runtime_adapter.py` | `_run_goal()` (line 365) | Replace sequential `for task in tasks` with topologically-ordered loop |
| `src/core/runtime_adapter.py` | module level | Add `_criteria_to_verifier_dict`, `_report_to_verification`, `_ExecResultLike`, `_topological_task_order`, `_plan_has_dependencies` |
| `src/core/verifier.py` | `RecipeVerifier.verify` (line 281) | NO change — consumed as-is |
| `src/core/adapters/goal_engine_adapter.py` | `_task_to_step` (line 162) | NO change — already provides `Step.dependencies` |
| `src/mekongcli/core/goal_engine/models.py` | `TaskGraph.ready_tasks` (line 112) | NO change — reference algorithm only |
| `tests/test_runtime_verify_merge.py` | new | Phase 1 tests |
| `tests/test_runtime_dag_order.py` | new | Phase 2 tests |
| `tests/test_runtime_multistep_cycle.py` | new | Phase 3 E2E test |
