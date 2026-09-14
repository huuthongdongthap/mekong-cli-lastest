# Lane E8 — Agent Loop E2E Hermetic (`mekong cook`) — Completion Report

**Date:** 2026-08-29
**Worktree:** `.claude/worktrees/super-command-2`
**Status:** COMPLETE

## Scope

Migrate the regular `mekong cook` command from the legacy Binh Phap
`RecipeOrchestrator` engine to the canonical `MekongCoreRuntimeImpl`
lifecycle, and add a hermetic E2E test suite proving the full agent loop.

## Files Modified

| File | Change |
|------|--------|
| `src/cli/cook_command.py` | Removed legacy `RecipeOrchestrator`/LLM-client imports. `cook` now builds the runtime via `_build_runtime()`, attaches `MissionTracer`, drives `runtime.start_mission()` + `runtime.run()`. `--dry-run` calls `runtime.goal()` + `runtime.plan()`. JSON output emits `tracer.stages`. Added `@require_tier(Tier.FREE)`. CLI surface (args/options/help) preserved byte-for-byte. |
| `src/core/runtime_adapter.py` | Stage recording (`_record_stage`) wired through the full lifecycle: goal→plan→delegate→observe→remember→commit→finish. **Bug fix:** dispatcher failures (dicts carrying `"error"`) were silently dropped and treated as success; now propagated into `Result.error` so the repair loop triggers truthfully. |
| `src/core/mission_tracer.py` | Added `record_stage()` and ordered `stages` list. Backward compatible — `log_step` callers unaffected. |

## Files Created

| File | Purpose |
|------|---------|
| `tests/test_cook_e2e_lifecycle.py` | Hermetic E2E suite (tmp_path isolation, no real repo). 6 tests covering: stage chain, telemetry sink, billing attempt, repair loop (≤3 retries), governance block (forbidden + review), dry-run plan-only. |

## Files Not Touched (Protected Paths)

`gateway.py`, `raas/nowpayments_*`, `api/billing_routes.py`,
`middleware/license_gate.py`, `lib/raas_gate/`, `.github/workflows/*`,
`exec_runtime/local.py`, and the Binh Phap `RecipeOrchestrator` engine
(kept as a legacy consumer, not deleted).

## Test Results

```
tests/test_cook_e2e_lifecycle.py ..........  6 passed
tests/test_run_command_wiring.py ..........  18 passed
tests/test_governance.py ................  24 passed
tests/test_cook_e2e_lifecycle.py + wiring + governance combined: 48 passed
```

**E8 suite (green): 6/6**

| Test | Assertions |
|------|-----------|
| `test_happy_path_records_stages_emits_and_commits` | Stages == [goal, plan, delegate, observe, remember, commit, finish]; `task_completed` + `run_completed` events observed; `record_usage` present; mission status `success`. |
| `test_cli_runner_invokes_cook_in_sandbox` | Typer `CliRunner` invokes `cook "echo hello"` → exit 0. |
| `test_repair_path_surfaces_terminal_error_after_retries` | Failing `execute()` triggers repair ≤4 attempts, surfaces `result.error`, mission status `failed`. |
| `test_forbidden_goal_blocked_by_governance` | `rm -rf /tmp/x` → error contains "Action forbidden". |
| `test_review_goal_blocked_without_auto_approve` | `deploy production build` → error contains "requires human approval". |
| `test_dry_run_does_not_execute` | `--dry-run` exits 0, prints "Dry run complete - no steps executed". |

## Lint

```
ruff check src/cli/cook_command.py tests/test_cook_e2e_lifecycle.py src/core/runtime_adapter.py
→ All checks passed! (exit 0)
```

## Known Issues

1. **`tests/test_orchestrator_integration.py` — 5 failures (pre-existing, out of scope).**
   Confirmed unchanged by stashing all E8 files; these fail on the baseline
   before E8 work. Not caused by this phase. Not modified (file ownership).

2. **Full-suite parity vs `.orchestrate/latest/failset_baseline.txt` not cleanly
   concluded.** The baseline lists 277 entries; a full `pytest` run currently
   produces a noisy set including environmental failures and unrelated
   modules. E8 files in isolation are green; the orchestrator subset is
   unchanged from baseline. No conclusion drawn, no unrelated failures
   masked — they are reported as-is.

## Evidence

- `tests/test_cook_e2e_lifecycle.py` — hermetic E2E suite, 6/6 green.
- `src/cli/cook_command.py` — canonical-runtime `cook`, CLI surface preserved.
- `src/core/runtime_adapter.py` — stage chain + dispatcher error propagation fix.
- `src/core/mission_tracer.py` — `record_stage()` + ordered `stages`.
- `.orchestrate/latest/reports/E8_cook_e2e.md` — this report.