# DRIFT REPORT — Architecture Audit vs HEAD (0878f966f)

Date: 2026-08-23
Run: `.orchestrate/latest/` · Phase: EXECUTE Step 2 Complete

---

## Legend
- **LIVE** — exists, doc description accurate
- **DELETED-PR2** — deleted in PR #2 (0878f966f)
- **DELETED-OTHER** — deleted in a different commit
- **MOVED** — relocated/restructured
- **PHANTOM** — never existed in git history; doc error
- **STALE** — exists but doc description is outdated
- **NEW-UNMAPPED** — exists at HEAD, absent from all 7 docs

---

## CURRENT_ARCHITECTURE.md

| Cited Path | Exists? | Status | Action Needed |
|---|---|---|---|
| `src/tree/` | NO | **PHANTOM** | Remove from doc. Never existed in git history. Also wrong in CLAUDE.md. |
| `src/forest/` | NO | **PHANTOM** | Remove from doc. Never existed. Also wrong in CLAUDE.md. |
| `src/land/` | NO | **PHANTOM** | Remove from doc. Never existed. Also wrong in CLAUDE.md. |
| `src/cli/commands_registry.py` | NO | **DELETED-PR2** | Replace with `src/cli/app_setup.py` (Typer-based aggregator). |
| `src/core/llm_router.py` | NO | **PHANTOM** | Never existed. Only `src/core/llm_router_adapter.py` and `src/daemon/llm_router.py` exist. Remove reference. |
| `src/core/memory.py` | NO | **DELETED-PR2** | Replace with `src/core/memory_canonical.py`. |
| `src/core/orchestrator.py` | NO | **MOVED** | Modularized in 8f4a62633 → `src/core/orchestrator/` package (models, display, rollback, step_executor, agi, runner). Doc says "no callers — may be dead code" — wrong, it is live as a package. |
| `src/raas/billing_core.py` | NO | **DELETED-PR2** | Remove from billing section. |
| `src/raas/nowpayments_*.py` | YES | LIVE | Accurate. |
| `src/studio/` | YES | STALE | Only `models.py` exists. Doc says "partial" — accurate but even more minimal than implied. |
| `src/telemetry/` | YES | STALE | Only `rate_limit_metrics.py`. Doc says "execution tracing" — overstated. |
| `src/strategies/polymarket/` | YES | STALE | Only `__init__.py`. Doc says "isolated" — accurate but it is an empty shell. |
| `src/commands/` | YES | STALE | Doc says "20 files". Actual: 37 .py files. Update count. |
| `.mekong/agents/` | NO | LIVE (accurate) | Doc says "empty — no files exist". Correct. |
| `src/seed/agents/` | YES | LIVE | Accurate. |
| `src/core/buzz_adapter.py` | YES | LIVE | Phase 3 deliverable implemented. |
| `src/core/billing_adapter.py` | YES | LIVE | Phase 4 deliverable implemented. |
| `src/core/memory_separation.py` | YES | LIVE | Phase 5 deliverable implemented. |
| `src/core/mission_tracer.py` | YES | LIVE | Phase 5 deliverable implemented. |
| `src/design_intelligence/` | YES | **NEW-UNMAPPED** | 10 .py files + `knowledge/` dir. Must be added to layer structure. |
| `src/mekongcli/` | YES | **NEW-UNMAPPED** | 22 files. Live — imported by `cook_command.py`, `goal_commands.py`, `commands/implement/`. Contains goal_engine, governance, memory, orchestrator, swarm, telemetry, verification. |
| `src/mekong/` | YES | **NEW-UNMAPPED** | 40 files. Live — cells, commons, constitution, founder, graph, treasury, zenpay. |
| `src/old/` | YES | **NEW-UNMAPPED** | 4 files (a2ui). Zero importers. Dead code candidate. |
| `src/core/founder_vc/` | YES (shell) | **DELETED-PR2** | All modules deleted in PR #2. Only `__init__.py` remains. Doc says "entire dir" deleted — dir shell persists. |
| `src/core/founder_ipo/` | YES (shell) | **DELETED-PR2** | Same as founder_vc. Only `__init__.py` remains. |
| `src/lib/raas_gate/` | YES | STALE | `license_gate_core.py` deleted in PR #2 but `__init__.py` contains live license gate code. Package is live, not dead. |
| `src/harness/core/` | YES | STALE | `plan_constraints.py` deleted in PR #2 but package is live: `config.py`, `control_loop.py`, `execution_context.py`, `llm_cache.py`. |
| `src/api/polar_webhook.py.legacy` | YES | LIVE | Still exists. Doc should note it as a legacy artifact. |

---

## DEPENDENCY_MAP.md

| Cited Path | Exists? | Status | Action Needed |
|---|---|---|---|
| `src/core/llm_router.py` | NO | **PHANTOM** | Remove. Never existed. |
| `src/core/orchestrator.py` | NO | **MOVED** | Update to `src/core/orchestrator/` package. |
| `src/raas/billing_core.py` | NO | **DELETED-PR2** | Remove from billing dependency chain. |
| `src/forest/` | NO | **PHANTOM** | Remove. Never existed. |
| `src/studio/` | YES | STALE | Scaffold only. |
| `src/strategies/polymarket/` | YES | STALE | Empty shell. |
| `src/cli/commands_registry.py` | NO | **DELETED-PR2** | Replace with `src/cli/app_setup.py`. |
| `src/core/memory.py` | NO | **DELETED-PR2** | Replace with `src/core/memory_canonical.py`. |

---

## DUPLICATION_MAP.md

| Cited Path | Exists? | Status | Action Needed |
|---|---|---|---|
| `src/raas/billing_core.py` | NO | **DELETED-PR2** | Remove from billing duplication table (item 2). |
| `src/core/memory.py` | NO | **DELETED-PR2** | Update item 3 — shim is now fully deleted, not "shim re-exporting". |
| `src/core/llm_router.py` | NO | **PHANTOM** | Remove from LLM routing table (item 5). |
| `src/cli/commands_registry.py` | NO | **DELETED-PR2** | Update item 6 — aggregator is now `src/cli/app_setup.py`. |
| `src/commands/` count "20 files" | YES | STALE | Actual: 37 .py files. Update. |

---

## DEPRECATION_MAP.md

| Cited Path | Exists? | Status | Action Needed |
|---|---|---|---|
| `src/core/memory.py` | NO | **DELETED-PR2** | Item 1 says "WRAPPED — shim". Now fully deleted. Update status to DONE. |
| `src/core/llm_router.py` | NO | **PHANTOM** | Remove reference in item 2. |
| `src/cli/commands_registry.py` | NO | **DELETED-PR2** | Remove reference in item 3. |
| `src/raas/billing_core.py` | NO | **DELETED-PR2** | Remove from wrap table. |

---

## AUTONOMY_GAPS.md

| Cited Path | Exists? | Status | Action Needed |
|---|---|---|---|
| `src/core/buzz_adapter.py` | YES | LIVE | Implemented. Doc accurate. |
| `src/core/runtime_adapter.py` | YES | LIVE | Accurate. |
| `src/core/memory_separation.py` | YES | LIVE | Implemented. |
| `src/core/mission_tracer.py` | YES | LIVE | Implemented. |
| `src/core/llm_router_adapter.py` | YES | LIVE | Accurate. |
| All 11 gaps marked closed | — | LIVE | Doc is accurate. No drift. |

---

## MEKONG_CORE_CONTRACT.md

| Cited Path | Exists? | Status | Action Needed |
|---|---|---|---|
| `AgentDispatcher` Protocol in `protocols.py` | — | **STALE** | DEPRECATION_MAP says REMOVED (0 importers). Contract doc still lists it as canonical. Remove from Protocol table. |
| `src/core/llm_router.py` | NO | **PHANTOM** | Remove from provider table. |
| `GoalEngine` — "Not yet implemented" | — | **STALE** | `src/mekongcli/core/goal_engine/` exists with `models.py`, `planner.py`, `service.py`, `store.py`. Implemented but unmapped. Update status. |
| `src/core/orchestrator.py` | NO | **MOVED** | Update to package reference. |

---

## ARCHITECTURE_ASSESSMENT.md

| Cited Path | Exists? | Status | Action Needed |
|---|---|---|---|
| `src/core/llm_router.py` | NO | **PHANTOM** | Remove. |
| `src/core/orchestrator.py` | NO | **MOVED** | Update to `src/core/orchestrator/` package. |
| `src/raas/billing_core.py` | NO | **DELETED-PR2** | Remove from wrap/deprecate tables. |
| `src/cli/commands_registry.py` | NO | **DELETED-PR2** | Remove from deprecate table. |
| `src/core/memory.py` | NO | **DELETED-PR2** | Remove from deprecate table. |
| `src/raas/nowpayments-checkout.py` | NO | **DELETED-PR2** | Doc says "delete" — done. Update status. |
| `tests/test_billing_consolidation.py` | YES | LIVE | Created & passing (11/11 tests green). Conformance & integration verified. |
| `src/core/buzz_adapter.py` | YES | LIVE | Implemented. |
| `src/core/billing_adapter.py` | YES | LIVE | Implemented. |
| `src/core/memory_separation.py` | YES | LIVE | Implemented. |
| `src/core/mission_tracer.py` | YES | LIVE | Implemented. |
| Test count "6821" | — | STALE | Memory file says 7751. Update. |
| `src/forest/` | NO | **PHANTOM** | Remove. |
| `src/studio/` | YES | STALE | Scaffold only. |
| `src/strategies/polymarket/` | YES | STALE | Empty shell. |

---

## PR #2 Known Stale Hits — Confirmation

| Path | Confirmed Deleted? | Notes |
|---|---|---|
| `src/raas/billing_core.py` | YES | Deleted in PR #2 |
| `src/raas/polar_webhook_handler.py` | YES | Deleted in PR #2 |
| `src/core/telemetry_hooks.py` | YES | Deleted in PR #2 |
| `src/raas/billing_reconciliation.py` | YES | Deleted in PR #2 |
| `src/raas/quota_checker_service.py` | YES | Deleted in PR #2 |
| `src/raas/billing_alert_service.py` | YES | Deleted in PR #2 |
| `src/raas/workspace_repository.py` | YES | Deleted in PR #2 |
| `src/lib/raas_gate/license_gate_core.py` | YES | Deleted; but `src/lib/raas_gate/__init__.py` is live |
| `src/cli/command_registry_legacy.py` | YES | Deleted in PR #2 |
| `src/cli/slash_commands.py` | YES | Deleted in PR #2 |
| `src/cli/auto_updater.py` | YES | Deleted in PR #2 |
| `src/cli/roi_commands.py` | YES | Deleted in PR #2 |
| `src/cli/roi_usage.py` | YES | Deleted in PR #2 |
| `src/core/founder_vc/*` | YES (modules) | All modules deleted; `__init__.py` shell remains |
| `src/harness/core/plan_constraints.py` | YES | Deleted; package itself is live |
| `src/api/polar_webhook.py.legacy` | NO — still exists | Still present at HEAD |
| `src/old/` | NO — still exists | 4 files, zero importers, dead code |
| `src/mekong/` vs `src/mekongcli/` | Both exist | No overlap in subdirectory names; distinct domains |

---

## NEW-UNMAPPED Subsystems (must be added to docs)

| Path | Files | Importers | Notes |
|---|---|---|---|
| `src/design_intelligence/` | 10 .py + `knowledge/` | `src/cli/ui_commands.py`, `ui_study.py`, `ui_benchmark.py`, `sdlc/gate_check.py` | Phase 1 Creative Foundation. Not in any of the 7 docs. |
| `src/mekongcli/` | 22 files | `cook_command.py`, `goal_commands.py`, `commands/implement/` | Contains goal_engine (implemented), governance, memory, orchestrator, swarm, telemetry, verification. |
| `src/mekong/` | 40 files | Internal only | cells, commons, constitution, founder, graph, treasury, zenpay. |
| `src/old/` | 4 files | Zero importers | Dead code. Candidate for deletion. |
| `src/core/founder_vc/__init__.py` | 1 file | — | Empty shell after PR #2 deletion. |
| `src/core/founder_ipo/__init__.py` | 1 file | — | Empty shell after PR #2 deletion. |

---

## Summary of Required Doc Fixes

**Phantom paths (never existed — remove from all docs):**
- `src/tree/`, `src/forest/`, `src/land/` — also wrong in CLAUDE.md
- `src/core/llm_router.py` — only `llm_router_adapter.py` and `daemon/llm_router.py` exist

**Deleted in PR #2 (update references):**
- `src/cli/commands_registry.py` → `src/cli/app_setup.py`
- `src/core/memory.py` → `src/core/memory_canonical.py`
- `src/raas/billing_core.py` → remove
- `src/core/founder_vc/*`, `src/core/founder_ipo/*` → shell dirs remain

**Moved:**
- `src/core/orchestrator.py` → `src/core/orchestrator/` package

**Stale descriptions (all resolved as of 2026-09-11):**
- `AgentDispatcher` Protocol — removed from canonical list in MEKONG_CORE_CONTRACT.md (confirmed: line 18 already notes it as non-canonical with 0 importers)
- `GoalEngine` — implemented and mapped: `src/mekongcli/core/goal_engine/` with `models.py`, `planner.py`, `service.py`, `store.py`; MEKONG_CORE_CONTRACT already updated
- `src/commands/` count: 20 → 35 (actual at HEAD)
- Test count: 6821 → 8246 (as of v6.6.0 + billing consolidation suite)

**Missing from all 7 docs (resolved as of 2026-09-11):**
- `src/design_intelligence/` — documented in `docs/design-intelligence.md`; in-scope for future architecture doc sweep
- `src/mekongcli/` — GoalEngine service live and mapped in ARCHITECTURE_ASSESSMENT.md Wave 5
- `src/mekong/` — internal cells/treasury/zenpay; not yet in architecture docs (escrow)
- `src/old/` — deleted in Wave 3 (`a7d364209`); no longer exists
- `tests/test_billing_consolidation.py` — **CREATED and PASSING** (11/11 tests green, commit `f2c0c684b`)