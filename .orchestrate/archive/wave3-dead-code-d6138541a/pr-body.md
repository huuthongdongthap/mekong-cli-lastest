# Wave 3: audit-verified dead-code deletion (assessment items 10–18)

## Summary

Implements Wave 3 from `docs/architecture/ARCHITECTURE_ASSESSMENT.md` "File-Level Implementation Order": removes audit-verified dead code and registers the three unregistered Typer apps. Follows Wave 1 (runtime safeguards, PR #4) and Wave 2 (masked imports, PR #5).

**Net diff: 35 files, +538/−3808.**

## Changes by item

| Item | Change | Commit |
|------|--------|--------|
| 10 | Delete `src/api/polar_webhook.py.legacy` + `tests/api/test_polar_webhook.py.legacy` (0 importers) | a7d364209 |
| 11 | Delete `src/old/` (a2ui copy, 0 importers; live package is `src/a2ui`) | a7d364209 |
| 12 | Delete `src/core/founder_vc`, `src/core/founder_ipo` (docstring-only shells) | a7d364209 |
| 14 | Delete `src/harness/sops-engine` (license-only stub), `src/harness/observability/raas_auth` (always-False stub; real client `src/core/raas_auth` untouched) | a7d364209 |
| 17 | Delete `workflows/scripts/zenos-full-redesign-wf_6f2b5978-3f8.js` artifact | a7d364209 |
| 13a | Delete `src/daemon/llm_router.py` (0 importers) | 3408f8905 |
| 13b | Delete `src/daemon/llm_config.py` + dead `run_llm()` in executor (its only consumer; audit claim was stale — noted in assessment) | 3408f8905 |
| 15 | Delete test-only `src/core/tracing.py` + its test file (23 tests; live `src/harness/observability/tracing.py` untouched) | 3408f8905 |
| 16 | Delete unused `setup_telemetry` / `sdk_setup.py`; cleaned re-exports in `telemetry/__init__.py` (gateway uses `telemetry_init.py`) | 3408f8905 |
| 18 | Fold root `cli/tui/streaming.py` + `cli/theme.py` → `src/cli/tui/`; delete dead `cli/ui/banner.py`+`help.py` (ESC-1 decision a); register billing/pev/usage Typer apps (33→36 groups); new surface test | 1446242e6, e8dc78908 |
| — | Extra fix: guard bmad loader in `build_app()` against importlib namespace pollution from fake `packages` module in test_plugin_binding | e8dc78908 |
| docs | Mark items 10–18 DONE in ARCHITECTURE_ASSESSMENT/DEPENDENCY_MAP/DEPRECATION_MAP with SHAs; ESC-3 correction (item 11 had all 4 files incl. component_helpers; proof was 0 importers); item-13 stale-claim note | a60ab1034, 21753f1a5, 9044f1164 |

## Included non-Wave-3 commit (disclosure)

`0693466f5` "fix: pin LC_ALL=C for git merge-tree CONFLICT parsing, drop stale hybrid-router test" (+4/−297) comes from a concurrent workstream sharing this branch and rides along under squash merge. Content verified independent of Wave 3 deletions.

## Verification

- **Test parity**: full suite = **223 failed / 7558 passed / 75 skipped** vs baseline 223 failed / 7576 passed — fail-set normalized diff vs frozen baseline (`failed_tests_head_0878f966f.txt`): **EMPTY, 223==223 exact**. Passed delta −18 explained: −23 removed test_tracing.py, +3 new wave3_surface tests, −21 removed stale platform-simulation test (concurrent commit), +23 tui-streaming tests preserved via import repoint.
- **Ruff**: All checks passed
- **Import smoke**: `src.gateway`, `src.daemon.executor`, `src.cli.tui.streaming`, `src.core.telemetry` ok; old paths gone
- **CLI smoke**: `build_app()` → 36 groups, billing/pev/usage present; `--help` shows them
- **Protected flows**: NOWPayments IPN chain + license gate chain cross-checked = zero overlap with deletion set

## Escrow / follow-ups

- Root `cli/` remainder (30 files: docs.py, strategy.py, developer.py, commands/, handlers/) — 0 importers verified; product-level decision escrowed to a later wave
- `tests/test_world_model.py::test_get_latest_snapshot` hangs in full-suite cwd scans ~300k entries (pre-existing; standalone passes) — recommend tmp_path or pruned os.walk
- `src/harness/observability/tracing.py` ≡ old `src/core/tracing.py` copy — Wave 4 dedup candidate

🤖 Generated with [Claude Code](https://claude.com/claude-code)
