# Deprecation Map

Refreshed: 2026-08-23 · HEAD: 0878f966f
Wave 3 dead-code deletions (sections 4–11, 13) executed 2026-08-25 · commits `a7d364209`, `3408f8905`, `1446242e6`, `e8dc78908`

## Resolved by Deletion (PR #2, 0878f966f)

| Former candidate | Resolution |
|---|---|
| Basic MemoryStore shim (former `core/memory.py`) | **DONE** — the 4-line shim re-exporting `src/core/memory_canonical.py` was fully deleted in PR #2. Importers now bind directly to `src/core/memory_canonical.py` or `src/core/memory_store.py` (see DUPLICATION_MAP item 3). |
| `raas/billing_core.py` | **DONE** — deleted in PR #2. `src/billing/` is now a pure re-export facade over `src/raas/billing_engine.py`, `billing_proration.py`, `billing_idempotency.py`, `billing_audit.py`. |
| `core/llm_router.py` | **N/A — PHANTOM** — never existed in git history. Only `src/core/llm_router_adapter.py` (live) and `src/daemon/llm_router.py` (dead, see candidates below) ever existed. Reference removed. |
| `commands_registry.py` (former cli-package registry) | **DONE** — deleted in PR #2. Aggregator is now `src/cli/app_setup.py` (Typer-based). |

---

## Candidates for Deprecation

### 1. Direct LLM Client Calls (src/core/llm_client.py)

**Status:** WRAPPED (2026-08-21) — re-verified at HEAD

**Current:** `LLMRouterAdapter` (`src/core/llm_router_adapter.py`) delegates to
`LLMClient` for all generation methods (`generate`, `stream`,
`structured_output`). `LLMClient` retains its real production logic (provider
failover, caching, hooks, circuit breaker) and its public API is unchanged.
~32 caller files continue to use `LLMClient` directly — they are not yet
migrated to the Protocol interface.

**Migration path:** Future — migrate remaining callers from `LLMClient` direct
imports to the `LLMRouter` Protocol via `LLMRouterAdapter`. Adapter is ready;
callers are the remaining work.

**Risk:** LOW — Adapter wrapping is live; caller migration deferred.

---

### 2. Dict-Based Prompt Storage (DEFAULT_PROMPTS in agent_dispatcher.py)

**Status:** DEFERRED (2026-08-20) — re-verified at HEAD

**Current:** `DEFAULT_PROMPTS` lives in `src/core/agent_dispatcher.py`. Live
importers: `src/core/agent_registry.py`, `src/core/agent_dispatcher.py`, and
tests. `.mekong/agents/` is empty/nonexistent.

**Migration path:** Create `.mekong/agents/*.md` as the single source of
truth, then auto-generate `DEFAULT_PROMPTS` at build time. Deferred — no
markdown source exists yet.

**Risk:** LOW — Deferred until markdown prompt files exist.

---

### 3. Legacy Billing Routes (vn_pilot_billing.py, vn_payments_routes.py)

**Status:** DEFERRED — MEDIUM RISK (2026-08-20) — re-verified at HEAD

**Current:** Four billing route families remain mounted in `src/gateway.py`:
`src/api/billing_routes.py` (Polar), `src/api/raas_billing_service.py`,
`src/api/vn_pilot_billing.py`, `src/api/vn_payments_routes.py` (VietQR) — plus
`src/raas/nowpayments_router.py` and `src/raas/revenue_router.py` (see
DUPLICATION_MAP item 2). All live with distinct importers.

**Migration path:** Merge `vn_pilot_billing.py` + `vn_payments_routes.py` into
`billing_routes.py`. Update imports. Deferred — requires dedicated review.

**Risk:** MEDIUM — VN pilot and payments routes are live revenue paths.

---

### 4. Legacy Polar Webhook Artifacts

**Status:** DONE — DELETED (2026-08-25, `a7d364209`)

**Resolution:** `src/api/polar_webhook.py.legacy` and
`tests/api/test_polar_webhook.py.legacy` deleted. 0 importers. Superseded by
`src/api/webhooks/router.py` → `src/raas/revenue_router.py` (mounted in
`src/gateway.py`; the old `polar_webhook_router` mount was already commented
out at `src/gateway.py:100`). Remaining `polar_webhook` matches are comments,
log filenames, DB table names, and unrelated live functions.

**Risk:** LOW — 0 importers; replacement path verified live.

---

### 5. src/old/ (Dead a2ui Copy)

**Status:** DONE — DELETED (2026-08-25, `a7d364209`)

**Resolution:** `src/old/` deleted. It was a complete 4-file copy of a2ui
(`__init__.py`, `components.py`, `component_helpers.py`, `renderer.py`).
0 importers; the live implementation is `src/a2ui/`. *(ESC-3 correction: the
copy was complete — it did NOT lack `component_helpers.py`; the dead-code
evidence is 0 importers.)*

**Risk:** LOW — 0 importers; exact duplicate of live code.

---

### 6. Empty Package Shells (founder_vc, founder_ipo, sops-engine)

**Status:** DONE — DELETED (2026-08-25, `a7d364209`)

**Resolution:** PR #2 had deleted all modules inside these packages, leaving
docstring-only shells: `src/core/founder_vc/__init__.py`,
`src/core/founder_ipo/__init__.py` (0 importers each), plus the 125-byte
`src/harness/sops-engine/__init__.py` stub. All three shell directories deleted.

**Risk:** LOW — 0 importers; no code inside.

---

### 7. Daemon LLM Router and Config

**Status:** DONE — DELETED (2026-08-25, `3408f8905`)

**Resolution:** `src/daemon/llm_router.py` and `src/daemon/llm_config.py`
deleted. The live routing path is `src/core/llm_router_adapter.py` →
`src/core/llm_client.py`. *(Claim-stale note: the audit cited "0 importers",
but `src/daemon/executor.py` still imported `ModelConfig` via the dead
`run_llm()` method — that import and the method were removed in the same
commit.)*

**Risk:** LOW — live routing path unaffected.

---

### 8. Harness raas_auth Stub

**Status:** DONE — DELETED (2026-08-25, `a7d364209`)

**Resolution:** `src/harness/observability/raas_auth/` (always-False stub,
single `__init__.py`) deleted. The real client is the `src/core/raas_auth/`
package (`raas_auth_client.py` + `auth_gateway_mixin.py`) with 9+ importers
(`permission_registry.py`, `feature_gates.py`, `command_authorizer.py`,
`gateway_client/`, `activate_commands.py`, and more). No harness code imported
the stub.

**Risk:** LOW — Stub returned always-False; real client is the live surface.

---

### 9. src/core/tracing.py

**Status:** DONE — DELETED (2026-08-25, `3408f8905`)

**Resolution:** `src/core/tracing.py` and its sole consumer
`tests/test_tracing.py` deleted together. Overlapped
`src/core/telemetry_collector.py`, the live trace-collection path. *(Note:
`src/harness/observability/tracing.py` is a separate, LIVE module and was not
touched.)*

**Risk:** LOW — Test-only consumer; overlap with live collector verified.

---

### 10. setup_telemetry (src/core/telemetry/sdk_setup.py)

**Status:** DONE — DELETED (2026-08-25, `3408f8905`)

**Resolution:** `setup_telemetry()` removed from `src/core/telemetry/__init__.py`
exports and `sdk_setup.py` deleted. It was never called anywhere; the gateway
uses `init_telemetry()` from `src/core/telemetry_init.py` instead
(`src/gateway.py:60,64`).

**Risk:** LOW — Exported but never invoked.

---

### 11. Root cli/ Package

**Status:** PARTIAL — tui/theme folded, rest escrowed (2026-08-25, `1446242e6` + `e8dc78908`)

**Resolution:** `cli/tui/streaming.py` and `cli/theme.py` were folded into
`src/cli/tui/` (which already had the real `router.py`); the `cli/ui/` shells
(`banner.py`, `help.py`) were dropped; `tests/test_tui_streaming.py` updated to
import from `src.cli.tui`. The broken `cli.tui.router` import in
`src/command_fabric/router.py` was repaired to point at `src/cli/tui/router.py`
(Wave 2 masked-import fix).

**Escrow (not deleted this wave):** the remaining root `cli/` —
`cli/commands/*` (9 files), `docs.py`, `strategy.py`, `developer.py`,
`handlers/`. Sole consumer is `tests/benchmark_cli.py` (standalone script, not
collected by pytest). Tracked in the wave-3 ship-report.

**Risk:** LOW — fold verified by 39 passing `test_tui_streaming` tests and
`import cli.tui.streaming` now failing as expected.

---

### 12. src/mekong/ vs src/mekongcli/

**Status:** KEEP BOTH (2026-08-23)

**Current:** Despite similar names, the two packages are verified DISTINCT
domains with zero subdirectory-name overlap:

| Package | Domain |
|---|---|
| `src/mekong/` (40 files) | cells, commons, constitution, founder, graph, treasury, zenpay |
| `src/mekongcli/` (22 files) | goal_engine, governance, memory, orchestrator, swarm, telemetry, verification |

`src/mekongcli/` is live — imported by `src/cli/cook_command.py`,
`src/cli/goal_commands.py`, and `src/cli/commands/implement/`.

**Migration path:** None — keep both. Add a naming note to
CURRENT_ARCHITECTURE.md so future readers don't treat them as duplicates.

**Risk:** LOW — No action required.

---

### 13. Unregistered CLI Apps (Decision Needed)

**Status:** DONE — REGISTERED (2026-08-25, `e8dc78908`)

**Resolution:** All three Typer apps registered in `src/cli/app_setup.py`
(`add_typer` at :127-129):

| File | Registered as |
|---|---|
| `src/cli/billing_commands.py` | `billing` |
| `src/cli/pev_commands.py` | `pev` |
| `src/cli/usage_commands.py` | `usage` |

Decision: register (not delete) — `billing` and `usage` are among the commands
advertised in `src/commands/COMMAND_REGISTRY.md`. Verified: `build_app()` +
3 `add_typer` → 36 groups, 0 duplicate names, 0 exceptions; a surface test
asserts the 3 groups appear in `build_app().registered_groups`.

**Risk:** LOW — registration smoke-tested.

---

## Completed (Historical)

### Duplicate NOWPayments Module (nowpayments-checkout.py)

**Status:** DONE (2026-08-20)

Deleted the hyphenated `nowpayments-checkout.py` and
`nowpayments-webhook-handler.py`; verified byte-identical to the underscore
versions (`src/raas/nowpayments_checkout.py`,
`src/raas/nowpayments_webhook_handler.py`) via `diff`/`md5`. Tests updated to
load the canonical underscore versions. Risk: LOW.

### Governance Binary Classification

**Status:** DONE (2026-08-20)

`Governance` has `ActionClass` enum (SAFE/REVIEW_REQUIRED/FORBIDDEN) in
`src/core/governance.py`; `GovernanceDecision` carries `action_class`,
`reason`, `requires_approval`, `approved`. Both `autonomous.py` and
`src/core/runtime_adapter.py` gate on `decision.action_class`. Risk: LOW.

### AgentDispatcher Protocol (duplicate definition)

**Status:** DONE (2026-08-20)

Removed the `AgentDispatcher` Protocol from `src/core/protocols.py` entirely
(0 importers). `AgentRegistry` (`src/core/agent_registry.py`) is the canonical
dispatch surface (`get()`, `list_agents()`, `discover()`, `get_meta()`);
`build_message_chain()` and `load_agent_prompt()` live in
`src/core/agent_dispatcher.py` as standalone functions. Risk: LOW.

---

## Not Deprecated (Keep As-Is)

| Component | Reason |
|-----------|--------|
| `src/core/memory_client.py` | NeuralMemoryClient may have unique vector features |
| `src/strategies/polymarket/` | Separate domain, not conflicting (empty shell — `__init__.py` only) |
| `src/studio/` | Video studio is a product vertical (scaffold: `models.py` only) |
| `src/mekong/` | Distinct domain from `src/mekongcli/` — verified, see item 12 |
| `src/mekongcli/` | Live goal-engine stack — imported by cook/goal/implement commands |
| `src/core/orchestrator/` | LIVE package (modularized in 8f4a62633: models, display, rollback, step_executor, agi, runner) — canonical for `mekong cook`, gateway, raas_router, telegram; 15+ importers. Removed from deprecation candidates. |
| `src/commands/` | 37 command modules; aggregator is `src/cli/app_setup.py` (53 live commands) |
| `src/db/tier_config_repository.py` | Rate-limiting config (DB-backed), distinct from `src/seed/config/tiers.py` pricing/credits |
| `engine/billing/tier_config.py` | Re-export façade forwarding to canonical `src/seed/config/tiers.py` (DUPLICATION_MAP Item 9) |
| `src/core/llm_client.py` | Real production LLM client with failover/caching; wrap behind adapter, do not replace |
