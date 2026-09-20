# Orchestration Task

> Generated: 2026-09-19
> Origin: `/orchestrate go next`

## Task (Vietnamese, original)

go next

## English interpretation

Continue the next improvement for Mekong CLI. All 7 development roadmap phases and 10 architecture gaps are marked complete. One known blocker remains: `tests/test_nl_routing.py` has multiple failures (38+ tests) caused by (1) `fuzzy_match()` signature mismatch — tests call `fuzzy_match(pattern, text)` but the implementation is `fuzzy_match(text, pattern)`, and (2) stale route expectations — tests reference route names like `ci-debugger`, `cicd-deploy`, `infra-provision`, `db-migrate`, `api-build`, `monitoring`, `metrics`, `logs-check`, `e2e-test`, `load-test`, `vuln-scan`, `secret-rotate`, `research`, `scout`, `analyze` that no longer exist in the routing table.

## Context

- Repo root: `/Users/macbook/mekong-cli` (Mekong CLI v6.0, Python + Typer, MIT).
- Current branch: `main` at `ba0f087ba` (1 commit ahead of origin/main — unpushed due to sandbox network restriction).
- Recent fix: `MEKONG_RAAS_DB` env var added to `src/raas/{tenant,credits,mission_store}.py` for test isolation.
- Known failures in `tests/test_nl_routing.py` (70 tests collected, ~38 fail):
  - `TestFuzzyMatch` — all fail with `TypeError: fuzzy_match() missing 1 required positional argument: 'text'` (signature mismatch).
  - `TestMatchRoutes::test_new_*` — 22 tests assert stale route names (`ci-debugger`, `cicd-deploy`, etc.) that don't exist in the current routing table.
  - `TestMatches` — 4 tests fail on edge cases (`test_empty_text_returns_false`, `test_empty_pattern_returns_false`, `test_whitespace_normalization`, `test_trailing_star_substring_hit`).
  - `TestMatchRoutes::test_none_returns_empty` — fails.
  - `TestMatchRoutes::test_duplicate_command_skipped_second_pass` — fails.
- Other known pre-existing failures (from prior orchestration): `tests/test_self_healing.py`, `tests/test_smart_router.py`.

## Non-goals

- Do NOT add new features — this is a test-debt cleanup task.
- Do NOT change routing behavior — update tests to match current implementation.
- Do NOT touch `.github/workflows/*`.
- Do NOT commit secrets / `.env*`.
- Do NOT break the 39-group invariant.

## Definition of Done

1. `tests/test_nl_routing.py` — all 70 tests pass.
2. `fuzzy_match` signature mismatch resolved (either fix implementation or update tests — whichever is correct based on how callers use it).
3. Stale route expectations updated to match current routing table.
4. Edge-case tests fixed (`test_empty_text_returns_false`, `test_empty_pattern_returns_false`, `test_whitespace_normalization`, `test_trailing_star_substring_hit`, `test_none_returns_empty`, `test_duplicate_command_skipped_second_pass`).
5. No regression: 39 groups, 0 ruff errors, targeted test suites green.
