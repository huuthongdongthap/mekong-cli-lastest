# Step 4 Consolidated Findings — 13 Categories Re-assessment at HEAD 0878f966f

Sources: Step 4 Fork 1 (cats 1-7, focus a/b) + Fork 2 (cats 8-14, focus c/d). All evidence verified by grep/read/cmp/runtime introspection.

## CRITICAL NEW DEFECTS (found this audit)

1. **`mekong run` production path BROKEN**: `src/commands/run.py:54-58` `_NullTelemetry` defines only `record_event()`, but `runtime_adapter.py:324,389` calls `self._telemetry.emit(...)` unconditionally → AttributeError at first observe(). Verified statically (`hasattr(t,'emit') == False`). Production constructor also omits `governance=`, `max_cost_usd=`, tracer → approval gate, cost guard, mission tracing all INERT in prod wiring.
2. **MCP capability adapter silently broken**: `src/core/adapters/mcp_capability_adapter.py:55` imports nonexistent `MCPServer` (class is `MekongMcpServer`, mcp_server.py:165) → try/except swallows → sync_from_mcp discovers ZERO tools. Second bug: handler lookup `_handle_{tool_name}` misses `cc_` prefix (line ~85). Tests mask with MagicMock.
3. **Daemon scheduler = unsandboxed arbitrary shell exec**: `src/daemon/scheduler.py:100` runs entire text of any file dropped in watch dir via `executor.run_shell()` — NO CommandSanitizer, NO allowlist, NO approval. Weakest link; full user privileges, 1800s timeout.
4. **Broken imports (masked)**: `src/command_fabric/router.py:25` imports nonexistent `cli.tui.router` (real: `src/cli/tui/router.py`) → ModuleNotFoundError verified. `src/cli/commands/implement/__init__.py:188` imports `SQLiteGoalStore` from wrong module (`verification` instead of `goal_engine`) → silent subprocess fallback. `src/commands/agi_bridge.py:24,34` spawns nonexistent `apps/openclaw-worker/task-watcher.js` → `mekong agi start` dead-on-arrival.

## Category Status Summary

| # | Category | Status | Severity |
|---|----------|--------|----------|
| 1 | Duplicated orchestration | UNCHANGED | HIGH |
| 2 | Dead code | IMPROVED (PR#2 swept; residue remains incl. 5 unregistered CLI apps, 16 zero-ref command modules, byte-identical planner) | MED-HIGH |
| 3 | Conflicting agent abstractions | UNCHANGED (3 AgentBase, 3 registries, mixed-stack CLI) | MED |
| 4 | Duplicated CLI surfaces | UNCHANGED (53 live commands, zero dup names; orphan modules + stale COMMAND_REGISTRY.md claim 43 wired, 16 advertised missing) | MED |
| 5 | Billing/payment duplication | IMPROVED (storage converged MCU→CreditStore; src/billing/ facade-only; tier-config duality remains) | MED |
| 6 | Cloudflare adapters | UNCHANGED (already adapter-shaped; core has zero CF SDK imports) | LOW |
| 7 | Core primitives | IMPROVED (9+1 Protocols live; runtime_adapter primitive-ready; MemoryStore 3-way split = open gap; mission_tracer lacks Protocol) | MED |
| 8 | Deprecation candidates | UNCHANGED (verdicts below) | LOW |
| 9 | Buzz integration gaps | UNCHANGED (callback fake — send_update never POSTs; no schema validation/auth; plan()=1-step stub; delegate()=_NullDispatcher raises) | MED |
| 10 | MCP gaps | WORSENED (silent import bug; no MCP client/consumer side; input_schema always {}) | HIGH |
| 11 | x402/MPP abstraction | UNCHANGED (settle_payment stub pending=True; NOWPayments hard-coded bypasses PaymentProvider protocol; estimate_cost silently zero) | MED |
| 12 | Unsafe autonomous paths | UNCHANGED (daemon scheduler worst; PEV shell OK-ish; tool_registry strict sanitizer SAFE; local_executor non-strict) | HIGH |
| 13 | Approval/risk gates | WORSENED (gates exist but prod wiring omits governance/max_cost_usd; dna manifests eval-time only; GOVERNANCE_AUTO_APPROVE env bypass; license gating INTACT post-deletion) | HIGH |
| 14 | State/memory ownership | UNCHANGED (protocols.MemoryStore aspirational — zero exact conformers; tenants.db 6 writer modules; mission traces in-memory only; mcu_billing docstring cites wrong db path) | MED |

## Key Detail Tables

### Orchestration stacks (Cat 1)
- Stack A `src/core/orchestrator/` RecipeOrchestrator — canonical for `mekong cook`, gateway, raas_router, telegram, agi_score (15+ importers)
- Stack B `src/mekongcli/core/` GoalEngine — `mekong goal`, `cook-auto*`, implement commands
- Stack C `src/harness/` PEV+swarm — `mekong swarm`, `agent assemble`; planner.py BYTE-IDENTICAL to src/core/planner.py (cmp verified); dag_scheduler.py is 19-line stub vs core's real 220-line scheduler; executor diverged (+860 diff lines)
- Stack D `src/daemon/` — scheduler/jidoka/mission_control isolated; only heartbeat_scheduler externally imported

### Dead-code verdicts (Cats 2/8/d)
| Candidate | Verdict | Evidence |
|---|---|---|
| src/api/polar_webhook.py.legacy (+ tests/api/test_polar_webhook.py.legacy) | DELETE | 0 importers; superseded by src/api/webhooks/router.py → revenue_router |
| src/old/ (a2ui copy) | DELETE | 0 importers; duplicates live src/a2ui |
| src/core/founder_vc/__init__.py + founder_ipo/__init__.py shells | DELETE | docstring-only, 0 importers |
| src/daemon/llm_router.py + llm_config.py | DELETE | 0 importers post-f7d420c75 |
| src/core/tracing.py | DEPRECATE→DELETE | test-only consumers; overlaps telemetry_collector |
| src/harness/sops-engine/ | DELETE | empty stub |
| src/harness/observability/raas_auth/ | DELETE | always-False stub; real client src/core/raas_auth.py has 9 importers |
| Root cli/ | KEEP-but-flag / partial | cli/tui/streaming.py test-only; router.py:25 broken import; fold cli.tui→src/cli/tui |
| src/cli/billing_commands.py, pev_commands.py, usage_commands.py | UNREGISTERED | full Typer apps never registered in app_setup.py |
| src/core/telemetry/sdk_setup.py setup_telemetry | DEAD | exported, never called (gateway uses telemetry_init.init_telemetry) |
| workflows/scripts/zenos .js | DELETE | zero references |

### Funnels (Focus a)
- Zalo OA: code intact (src/commands/zalo_oa.py + integrations/zalo.py, tests pass) but NOT registered in app_setup — reachable only via `python -m`
- Tax & Accounting: thue_dnvn.py/ke_toan.py pure libraries, no main(), no CLI registration; tests pass (373 green)
- Sophia: NO command surface in repo (apps/sophia-ai-factory body absent); nlp_commander keyword routing only
- PR#2 deleted src/cli/vn_setup.py (-189L) — the one true funnel orphan (wizard gone)
- 16 advertised commands MISSING from live CLI: vn-setup, billing, trace, license, tier-admin, monitor, usage, auth, raas, sync-raas, activate, deploy-all, test, lint, clean, ci
- CLAUDE.md stale: tree/forest/land don't exist; "43 commands" vs 53 actual

### Autonomy gaps (Focus c) — 11/11 STILL CLOSED, none regressed by PR#2
1 Buzz Adapter CLOSED-weakened (callback never transmitted) · 2 Stream/Structured CLOSED-partial (stream yields 1 chunk) · 3 Memory Separation CLOSED · 4 Mission Observability CLOSED-telemetry_hooks deletion did NOT break (mission_tracer+collector intact; caveat: in-memory only, plain run() never starts mission) · 5 Approval Gate CLOSED-class/inert-wiring · 6 Cost Limit CLOSED-class/inert-wiring · 7 Retry Limit CLOSED (_MAX_REPAIR_ATTEMPTS=3) · 8 Memory Ownership CLOSED-within-runtime · 9 Capability Ownership/Expiry CLOSED · 10 Trace Correlation CLOSED (mission_id=None caveat plain run()) · 11 Cost-in-Telemetry CLOSED
License gating post-license_gate_core-deletion: INTACT (inline in src/lib/raas_gate/__init__.py:64-243; middleware license_gate.py:52; engine/license/)
Cost-guard commits 9dc6c6237+850f25acc: both ancestors of HEAD, code present but inert in prod wiring

### Memory store map (Cat 14)
goals.sqlite3→SQLiteGoalStore (clean single writer) · ~/.mekong/raas/tenants.db→CreditStore (6 writer modules, one DB) · seed memory /tmp/seed_memory.db default (fragile) · memory_canonical YAML+vector (~20 consumers) vs memory_store JSONL (design_intelligence, dispatcher, memory cmd) vs protocols.MemoryStore Protocol (store/retrieve/delete/search — ZERO exact conformers) · mission_tracer in-memory only · ScopedMemoryStore behind MemorySeparation

### design_intelligence (Focus b) — COMPLIANT, LOW
design: namespace discipline ✅, advisory-only deploy hook ✅ (gate_check prints advice, no subprocess), does NOT import protocols.py (deliberate concrete binding to JSONL memory_store), exactly 4 consumers (ui_commands/ui_study/ui_benchmark/gate_check), 140 tests

### MCP state (Cat 10)
25 tools exposed via FastMCP stdio/SSE (`python -m src.core.mcp_server`); consumable AS server ✅; capability-sync adapter BROKEN (import bug); NO MCP client side (cannot consume external servers); input_schema always {}

### x402/MPP (Cat 11)
BillingMeter (:162-168) + PaymentProvider (:206-212) Protocols exist; BillingAdapter delegates settle_payment to stub (pending=True); NOWPayments mounted directly in gateway.py:34,109 BYPASSING protocol; missing: HTTP-402 middleware, receipt verification, idempotency keys, currency conversion, concrete PaymentProvider impls

### Buzz gaps (Cat 9)
BuzzAdapter.receive_goal/send_update/receive_feedback exist (buzz_adapter.py:26-67); run_from_payload wraps (runtime_adapter.py:191-212); missing: real async callback POST (send_update builds dict only), payload schema validation beyond goal presence, auth/HMAC, capability negotiation; loop stages: execute/observe/verify/repair/remember/commit REAL, plan()=single-step stub, delegate()=all-to-one-agent stub (prod _NullDispatcher raises NotImplementedError)

### Unsafe paths detail (Cat 12)
daemon scheduler run_shell: NO sanitizer/allowlist/approval, file-content-as-command · pev _execute_shell_step: CommandSanitizer + shlex + retries capped (SAFE-ish; backtick extraction from LLM text = sanitizer sole defense) · tool_registry shell:run: CommandSanitizer strict FAIL-CLOSED + 30s timeout (SAFE) · mekongcli local_executor: CommandSanitizer NON-STRICT + 60s (weaker) · No OS-level sandboxing anywhere

### Gate wiring (Cat 13)
Governance classify/request_approval implemented (governance.py:28-134); runtime gates at runtime_adapter.py:254-278 IF injected; prod constructor run.py:37-46 omits governance/max_cost_usd/tracer; dna manifests enforced ONLY in evals (solo_ceo.py); HARNESS.md high-risk gates + --ceo-override NOT implemented anywhere
