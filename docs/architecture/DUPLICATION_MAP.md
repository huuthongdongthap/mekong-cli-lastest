# Duplication Map

Refreshed: 2026-08-23 · HEAD: 0878f966f

## Active Duplications

### 1. Duplicated AgentBase / AgentRegistry Abstractions

**Status:** RESOLVED (2026-09-10) — converged onto canonical core implementations

**Resolution:**
- `src/harness/agents/base.py` converted into a backward-compatible re-export façade forwarding directly to canonical `src.core.agent_base:AgentBase`, `Task`, `Result`, `TaskStatus`.
- `src/harness/agents/registry.py` converted into a backward-compatible re-export façade forwarding directly to canonical `src.core.agent_registry:AgentRegistry`, `AgentMeta`, `get_registry`.
- Single authoritative agent contract enforced across core runtime and harness layers while preserving complete compatibility for existing callers.

---

### 2. Billing / Payment Duplication

**Status:** RESOLVED (2026-09-10) — storage unified, NOWPayments routed through PaymentProvider protocol, CLI commands registered

**Resolution:**
- Storage converged: `MCUBilling` backed by `CreditStore` (`src/raas/credits.py`) via SQLite WAL.
- `src/raas/nowpayments_router.py` updated to route IPN callbacks through `NowPaymentsProvider` (`PaymentProvider` Protocol adapter).
- `src/cli/billing_commands.py` verified mounted and active in `src/cli/app_setup.py:build_app()`.
- PaymentProvider protocol compliance verified with golden tests and end-to-end delegation tests.

---

### 3. Memory Store — Three-Way Split

**Status:** RESOLVED (2026-09-10) — canonical store & JSONL adapter both satisfy protocols.MemoryStore

**Resolution:**
- `src/core/memory_canonical.py:MemoryStore` retrofitted with `store()`, `retrieve()`, `delete()`, and `search()`, satisfying `protocols.MemoryStore` runtime checkable protocol natively.
- Byte-exact base64 encoding guarantees arbitrary binary preservation across storage/retrieval.
- TTL expiry support integrated via `expires_at` metadata in entry context.
- Point deletion from `VectorMemoryStore` synchronized on `delete(key)`.
- `src/core/adapters/jsonl_memory_adapter.py:JsonlMemoryAdapter` formalizes JSONL as a second conformant backend.
- `MemoryStoreAdapter` and `MemoryStoreConformant` unified to delegate directly to canonical methods.
- Runtime conformance tests in `tests/test_memory.py` and `tests/ports/test_memory_store_conformance.py` pass 100%.

---

### 4. Observability Assets (Grafana Dashboards / Provisioning)

**Status:** IMPROVED (2026-09-10) — nested duplicate directories pruned

**Current:** Previously, three copies of the same dashboard JSON and provisioning YAML existed.
The accidental nested duplicate directories (`src/harness/observability/dashboards/dashboards/`
and `src/harness/observability/provisioning/provisioning/`) have been removed.

Root `observability/dashboards/` and `src/harness/observability/dashboards/` remain as
canonical and harness-adjacent copies. Compose and collector configs:
root `observability/docker-compose.observability.yml` + `prometheus.yml` + `otel-collector-config.yaml`
vs `src/harness/observability/docker-compose.yml` + `prometheus.yml` + `otel-collector.yaml`.

**Recommendation:** Maintain root `observability/` as canonical; keep harness copies aligned.

**Risk:** LOW — Static assets; verified zero references to nested directories.

---

### 5. LLM Routing & PEV Engine Convergence

**Status:** RESOLVED (2026-09-10) — harness PEV duplicates merged into core

**Resolution:**
- `src/harness/pev/planner.py` deleted; consumers import canonical `src/core/planner.py`.
- `src/harness/pev/verifier.py` merged into `src/core/verifier.py:RecipeVerifier` and deleted.
- `src/harness/pev/dag_scheduler.py` unified to delegate directly to `src/core/dag_scheduler.py:DAGScheduler`.

---

### 6. CLI Command Surfaces

**Status:** RESOLVED (2026-09-10) — unified on `src/cli/app_setup.py` & `workflow_commands.py`

**Resolution:**
- Canonical single aggregator is `src/cli/app_setup.py` (Typer-based, 39 registered groups, 128 commands).
- Natural language bilingual (VI/EN) router ported directly into canonical `src/cli/workflow_commands.py:ask_cmd`, dispatching leaf subcommands (`cook`, `debug`) and gracefully falling through for command groups (`plan`, `deploy`).
- `src/commands/core_commands.py` converted to backward-compatible deprecation shim forwarding to `src.cli.app_setup.build_app()`.
- `tests/integration/test_ask_routing.py` repointed directly to canonical `src.cli.app_setup.build_app()`.
- `src/commands/COMMAND_REGISTRY.md` updated to match `build_app()` command tree (39 groups, 128 commands).
- `billing_commands`, `pev_commands`, and `usage_commands` verified registered in `src/cli/app_setup.py`.

---

### 7. Verification Layers

**Status:** RESOLVED (2026-09-10) — RecipeVerifier unified into core and integrated into autonomous runtime execution loop

**Resolution:**
- `RecipeVerifier` merged into canonical `src/core/verifier.py` (PR #14, Super Command #8).
- Merged into `MekongCoreRuntimeImpl.verify()` via `_criteria_to_verifier_dict` and `_ExecResultLike` adapter, validating exit codes, pattern regexes, and file presence.
- Autonomous loop implements full `execute -> verify -> repair` cycle with four strategies (`RETRY`, `FALLBACK`, `ESCALATE`, `ROLLBACK`).
- Downstream task cancellation wired through `DAGScheduler.mark_failed` to prevent cascading runs on upstream verification failures.
Remaining verification layers:

| Layer | Location | Role |
|---|---|---|
| `RecipeVerifier` | `src/core/verifier.py` | Canonical verifier for orchestrator and runtime |
| `VerificationPipeline` | `src/mekongcli/core/verification/` | Goal-engine verification gates |
| `PostGate` | `src/daemon/gate.py` | Daemon post-execution gate |

---

### 8. Orphan Command Modules in src/commands/

**Status:** RESOLVED (2026-09-10) — dead stubs deleted, funnels reconnected, core shimmed

**Resolution:**
- Reconnected Vietnam business funnels (`zalo_oa.py`, `thue_dnvn.py`, `ke_toan.py`) to the CLI binary via `src/cli/funnel_commands.py` (`zalo-oa`, `thue`, `ke-toan`).
- Pruned zero-reference empty dead stubs `src/commands/ci.py` and `src/commands/env.py`.
- Deprecated `src/commands/core_commands.py` to forward to canonical `src.cli.app_setup:build_app()`.

---

### 9. Tier Configuration & Rate Limiting Duality

**Status:** RESOLVED (2026-09-10) — unified into canonical `src/seed/config/tiers.py` with backward-compatible re-export façade

**Resolution:**
- Reconciled duality between legacy `engine/billing/tier_config.py` and canonical `src/seed/config/tiers.py`.
- Canonicalized `TierKey` with `Tier = TierKey` alias, case-insensitive and legacy alias lookup via `_missing_`.
- Consolidated `RateLimitConfig`, `TierRateLimitConfig`, `DEFAULT_TIER_CONFIGS`, `get_tier_config()`, and `get_preset_config()` directly into `src/seed/config/tiers.py`.
- Converted `engine/billing/tier_config.py` into a thin re-export façade exporting all symbols with zero regression to external consumers.
- Upgraded `LicenseEnforcer` to enforce monotonic 6-tier hierarchy (`FREE: 0, TRIAL: 1, STARTER: 2, GROWTH: 3, PRO: 4, ENTERPRISE: 5`).
- Conformance verified with dedicated test suite `tests/test_tier_config_conformance.py` (28/28 tests passing).

