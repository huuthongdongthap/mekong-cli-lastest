# Dependency Map

Refreshed: 2026-08-23 · HEAD: 0878f966f

## Core Protocol Dependencies

```
protocols.py (canonical)
  ├── capability.py (re-exported)
  ├── runtime_adapter.py (imports Plan, PlanStatus, Step)
  ├── llm_router_adapter.py (imports LLMRouter)
  ├── mcp_capability_adapter.py (imports Capability)
  ├── billing_adapter.py (imports PaymentResult, QuotaStatus)
  ├── memory_store_adapter.py (imports MemoryHit)
  └── tests/test_*.py (import Protocol types)
```

Note: the `AgentDispatcher` Protocol was removed from `protocols.py`; the agent system now binds through `src/core/agent_dispatcher.py` (concrete, JSONL memory_store-backed).

## Runtime Dependency Chain

```
main.py / gateway.py
  ├── app_setup.py (Typer CLI dispatch — replaced commands_registry.py, deleted in PR #2)
  │     └── 53 live top-level commands (src/cli/*.py, src/commands/*.py)
  ├── runtime_adapter.py
  │     ├── protocols.py (MekongCoreRuntime Protocol)
  │     ├── memory_separation.py (MemoryTier)
  │     ├── llm_router_adapter.py
  │     ├── capability.py (CapabilityBus)
  │     ├── memory_store_adapter.py
  │     ├── verifier.py
  │     └── mission_tracer.py + telemetry_collector.py
  └── api/gateway routes (FastAPI)
        ├── billing_routes.py → services/polar_client.py
        ├── raas_billing_service.py → raas/billing_engine.py
        └── vn_payments_routes.py → raas/nowpayments_router.py
```

## Orchestrator (LIVE package)

`src/core/orchestrator/` is a live package (modularized from the former single file), NOT dead code. Modules: `runner.py` (RecipeOrchestrator), `step_executor.py`, `models.py`, `rollback.py`, `agi.py`, `display.py`.

14 src importers (grep-verifiable):

| Importer | Path |
|---|---|
| cook command | `src/cli/cook_command.py` |
| CLI helpers | `src/cli/helpers.py` |
| pev commands | `src/cli/pev_commands.py` |
| system commands | `src/cli/system_commands.py` |
| workflow commands | `src/cli/workflow_commands.py` |
| core commands | `src/commands/core_commands.py` |
| RaaS router | `src/api/raas_router.py` |
| AGI score | `src/core/agi_score.py` |
| gateway | `src/core/gateway/__init__.py`, `src/core/gateway/gateway_main.py` |
| rollback | `src/core/rollback.py` |
| telegram | `src/core/telegram_bot/bot.py`, `src/core/telegram_bot/formatters.py`, `src/core/telegram_handlers.py` |

Plus 10 test files under `tests/`.

## Billing Dependency Chain

```
mcu_billing.py (MCUBilling singleton)
  ├── raas/credits.py (CreditStore — SQLite WAL, mcu_billing.py:150-153)
  ├── db/schema.py (tier config, usage records)
  └── protocols.py (PaymentProvider Protocol)

billing_adapter.py (BillingAdapter — unified billing interface)
  ├── mcu_billing.py (wraps MCUBilling)
  └── protocols.py (PaymentResult, QuotaStatus)

raas/billing_engine.py
  ├── db/repository.py (LicenseRepository)
  ├── core/auth_tenant.py (derive_tenant_id)
  └── core/usage_metering.py (UsageEvent)

raas/billing_idempotency.py → billing_adapter.py
raas/nowpayments_webhook_handler.py → NOWPayments IPN
```

Note: `billing_core.py` was deleted in PR #2; BillingAdapter + MCUBilling (SQLite WAL via CreditStore) replaced it.

## Agent System Dependencies

```
agent_registry.py (AgentRegistry)
  ├── core/agent_base.py (AgentBase)
  ├── seed/agents/*.py (AgentBase subclasses)
  └── .mekong/agents/*.md (prompt files)

agent_dispatcher.py (concrete dispatcher)
  └── core/memory_store.py (JSONL MemoryStore)
```

## Memory Dependencies

```
memory_store_adapter.py (MemoryStoreAdapter)
  ├── core/memory_canonical.py (MemoryStore — canonical, YAML+vector)
  └── core/protocols.py (MemoryHit)

memory_canonical.py — ~20 consumers (grep-verifiable)
memory_store.py (JSONL) — consumers: agent_dispatcher.py, src/cli/commands/memory.py, design_intelligence/design_memory.py
memory_client.py (NeuralMemoryClient) / memory_bridge.py (MemoryBridge Protocol) / memory_scope.py (ScopedMemoryStore)
```

## Cross-Subsystem Edges (added at this refresh)

| Edge | Evidence |
|---|---|
| `mcu_billing.py` → `raas/credits.py` CreditStore | `mcu_billing.py:150-153` |
| `harness/pev/planner.py` byte-identical to `core/planner.py` | `cmp` verified (exit 0) |
| `design_intelligence/design_memory.py` → `core/memory_store.py` (JSONL) | `design_memory.py:20` |
| `mekongcli/core/goal_engine/service.py` → `core/memory_canonical.py` | `service.py:13` |

## Key External Dependencies

| Module | External Dependency | Purpose |
|--------|--------------------|---------|
| llm_router_adapter.py | OpenRouter API | LLM routing |
| llm_client.py | anthropic/openai libs | Direct LLM calls |
| mcp_server.py | MCP protocol | Tool execution |
| nowpayments_*.py | NOWPayments API | Crypto payments |
| db/schema.py | SQLite/Postgres | Data persistence |
| gateway.py | FastAPI, uvicorn | API server |

Note: the Inngest integration cited in earlier docs has zero references in `src/` at HEAD and was removed from this table. The phantom `forest` layer never existed and is removed.

## Circular Dependency Risk

- `protocols.py` re-exports `CapabilityBus` from `capability.py` — safe (one-way)
- `runtime_adapter.py` imports from `protocols.py` only — safe
- `mcp_capability_adapter.py` imports from both `capability.py` and `protocols.py` — safe
- No identified circular dependencies in Phase 2 additions

## Orphaned/Disconnected Components

Verdicts per `.orchestrate/latest/step4_findings.md` dead-code analysis. Wave 3 deletions executed 2026-08-25 (commits `a7d364209`, `3408f8905`, `1446242e6`, `e8dc78908`).

| Component | Status | Verdict |
|-----------|--------|-------|
| `src/daemon/llm_router.py` + `src/daemon/llm_config.py` | **REMOVED** (`3408f8905`) | Deleted — zero importers post-f7d420c75 (executor.py `ModelConfig` import via dead `run_llm()` removed same commit) |
| `src/core/tracing.py` | **REMOVED** (`3408f8905`) | Deleted with its test-only consumer `tests/test_tracing.py` — overlapped telemetry_collector. (`src/harness/observability/tracing.py` is a separate live module, untouched.) |
| `src/harness/sops-engine/` | **REMOVED** (`a7d364209`) | Deleted — empty stub |
| `src/harness/observability/raas_auth/` | **REMOVED** (`a7d364209`) | Deleted — always-False stub; real client is `src/core/raas_auth/` (9 importers) |
| Root `cli/` | **PARTIAL** (`1446242e6`) | `cli/tui/streaming.py` + `theme.py` folded into `src/cli/tui/`; `cli/ui/` shells dropped. Remaining root `cli/` (commands/, docs.py, strategy.py, developer.py, handlers/) kept — sole consumer is standalone `tests/benchmark_cli.py` (escrow) |
| `src/cli/billing_commands.py`, `src/cli/pev_commands.py`, `src/cli/usage_commands.py` | **REGISTERED** (`e8dc78908`) | Registered as `billing`/`pev`/`usage` Typer apps in `src/cli/app_setup.py` (:127-129) |
| `src/studio/` | Partial | Video studio scaffold only (`models.py`) |
| `src/strategies/polymarket/` | Isolated | Empty shell (`__init__.py` only) |
| `src/old/` | **REMOVED** (`a7d364209`) | Deleted — zero importers, duplicated live `src/a2ui` (complete 4-file copy incl. `component_helpers.py`) |
| `src/core/founder_vc/__init__.py` + `src/core/founder_ipo/__init__.py` | **REMOVED** (`a7d364209`) | Deleted — docstring-only shells after PR #2 module deletion |
| `src/api/polar_webhook.py.legacy` | **REMOVED** (`a7d364209`) | Deleted (with `tests/api/test_polar_webhook.py.legacy`) — superseded by `src/api/webhooks/router.py` |
| `src/core/telemetry/sdk_setup.py` `setup_telemetry` | **REMOVED** (`3408f8905`) | Deleted — exported, never called (gateway uses `telemetry_init.init_telemetry`) |
