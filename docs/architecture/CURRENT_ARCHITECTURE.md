# Current Architecture (Post-Phase 5 & Phase 6)

Refreshed: 2026-09-14 · HEAD: 81825c8bd

## Overview

Mekong CLI v6.0 is an AI-operated business platform for Vietnamese one-person companies. The codebase is a single Python repository with ~830 source files under `src/`, ~376 test files, and multiple entry points.

## Layer Structure

```
mekong (CLI) / api-gateway (FastAPI :8000)
  src/api/          — 37 REST route modules (raas, billing, vn_pilot, webhooks, etc.)
  src/cli/          — Typer CLI: app_setup.py aggregator + command modules
  src/commands/     — 38 command modules (run, deploy, zalo_oa, thue_dnvn, ke_toan, ...)
  src/core/         — Protocols + implementations (runtime, llm, billing, memory, orchestrator)
  src/services/     — External service clients (Polar, org service)
  src/seed/         — Auth, DB, config, agent definitions
  src/raas/         — RaaS billing engine + NOWPayments integration + CreditStore
  src/studio/       — Video generation studio (models.py only)
  src/telemetry/    — rate_limit_metrics.py only
  src/db/           — Database ORM + migrations
  src/gateway.py    — Gateway entry point
  src/main.py       — Main entry point
```

Note: the `tree`, `forest`, and `land` layers cited in earlier docs never existed in git history and have been removed from this document.

## Key Components

### CLI Entrypoint
- `src/main.py` → `src/cli/app_setup.py` — Typer aggregator registering 39 live Typer command groups (including Vietnam funnels `zalo-oa`, `thue`, `ke-toan`, `billing`, `pev`, `usage`, and `deploy`).
- Command modules live in `src/cli/*.py` (cook_command, goal_commands, ui_commands, billing_commands, funnel_commands, etc.) and `src/commands/*.py` (sophia_video, deploy, zalo_oa, thue_dnvn, ke_toan, etc.).
- Sub-apps are mounted cleanly: e.g., `sophia_video_app` is mounted under `tools_app` as `mekong tools video` preserving the strict 39-group total count.

### Core Runtime
- `src/core/runtime_adapter.py` — `MekongCoreRuntimeImpl` implements the 10-step autonomous loop (run, goal, context, plan, delegate, execute, observe, verify, repair, remember, commit) with topological DAG task scheduling and autonomous recovery cycle (RETRY, FALLBACK, ESCALATE, ROLLBACK)
- `src/core/governance.py` — `Governance` class with SAFE/REVIEW_REQUIRED/FORBIDDEN classifications
- `src/core/orchestrator/` — LIVE package (modularized from the former single-file orchestrator): `runner.py` (RecipeOrchestrator), `step_executor.py`, `models.py`, `rollback.py`, `agi.py`, `display.py`. Imported by 14 src modules (cook_command, gateway, raas_router, telegram, agi_score, ...) plus 10 test files — NOT dead code.

### Protocol Layer
- `src/core/protocols.py` — structural Protocols + CapabilityBus + PaymentProvider + GoalEngine + MemoryStore + LLMRouter
- `src/core/capability.py` — Capability dataclass + CapabilityBus Protocol
- `src/core/llm_router_adapter.py` — Adapter implementing LLMRouter Protocol with native token-by-token streaming, SSE line-by-line parsing in `OpenAICompatibleProvider`, circuit breaker provider failover in `LLMClient`, and backward compatibility for test mocks
- `src/core/adapters/mcp_capability_adapter.py` — MCP → Capability bridge (repaired in PR #4/5: imports `MekongMcpServer`, respects `cc_` prefix)

### Agent System
- `src/core/agent_registry.py` — AgentRegistry (list, list_agents, get, register)
- `src/seed/agents/` — Agent definitions (tester, cto, cso, etc.)
- `.mekong/agents/` — Markdown agent prompt files (empty — no files exist)

### Billing
- `src/core/mcu_billing.py` — MCUBilling singleton; storage backed by `src/raas/credits.py` CreditStore (SQLite WAL, `mcu_billing.py:150-153`)
- `src/core/billing_adapter.py` — BillingAdapter wrapping MCUBilling; the unified billing interface (replaced the deleted `billing_core.py`)
- `src/seed/config/tiers.py` — Consolidated single source of truth for tiers, pricing, MCU allocations, and rate limits (6-tier monotonic hierarchy: FREE, TRIAL, STARTER, GROWTH, PRO, ENTERPRISE)
- `src/raas/billing_engine.py` — RaaS billing core
- `src/raas/nowpayments_*.py` — NOWPayments integration conforming to `protocols.PaymentProvider`
- `src/api/billing_routes.py` — Billing API routes

### Memory
- `src/core/memory_canonical.py` — canonical `MemoryStore` satisfying `protocols.MemoryStore` runtime checkable protocol with exact base64 preservation and TTL expiry
- `src/core/adapters/jsonl_memory_adapter.py` — `JsonlMemoryAdapter` providing conformant second backend
- `src/core/protocols.py` — `MemoryStore` Protocol (store/retrieve/delete/search) with two conformant implementations
- `src/core/memory_client.py` — NeuralMemoryClient
- `src/core/memory_bridge.py` — MemoryBridge Protocol
- `src/core/memory_store_adapter.py` — Adapter bridging to MemoryStore
- `src/core/memory_scope.py` — ScopedMemoryStore

### Observability
- `src/telemetry/rate_limit_metrics.py` — rate limit metrics collection
- `src/core/mission_tracer.py` + `src/core/telemetry_collector.py` — mission tracing and telemetry collection wired into production runtime
- `src/core/verifier.py` — Output verification (merged with `RecipeVerifier`)

### Integration Points
- Cloudflare: unified in `src/cli/sdlc/deploy.py` & `src/commands/deploy.py` (`mekong deploy run/status/rollback` with dry-run support and flag smuggling defense)
- MCP: `src/core/mcp_server.py` (25 tools via FastMCP stdio/SSE) + `src/core/adapters/external_mcp_client.py` (client-side third-party server consumption)
- OpenRouter: LLM routing via `src/core/llm_router_adapter.py`
- NOWPayments: IPN webhook → tier activation via `protocols.PaymentProvider`
- VietQR / PayOS: Webhook HMAC verification and automated banking settlement for Vietnam SMBs

## Unmapped Subsystems

| Path | Contents | Status |
|---|---|---|
| `src/design_intelligence/` | 10 .py + `knowledge/` | LIVE, contract-compliant; integrated with Sophia Video for brand token styling |
| `src/services/sophia_video_service.py` | SophiaVideoService RaaS engine | LIVE; avatar/voice/template catalogs, Design DNA tokens, MCU billing, dry-run container |
| `src/mekongcli/` | 22 files — GoalEngine stack (goal_engine, governance, memory, orchestrator, swarm, telemetry, verification) | LIVE; imported by cook_command, goal_commands, commands/implement |
| `src/mekong/` | 38 .py — particle/founder/treasury/zenpay domain | LIVE, internal only |
| `src/old/` | 4 files (a2ui copy) | DELETED in Wave 3 (PR #6) |
| `src/daemon/` | scheduler/jidoka/mission_control | Sandboxed with CommandSanitizer |

## Former Critical Defects (All Closed)

1. **`mekong run` production path broken** — **CLOSED** (PR #4). `_NullTelemetry` replaced with `TelemetryCollector` with real `emit()`. Runtime constructor injects `governance`, `max_cost_usd`, and `mission_tracer`.
2. **MCP capability adapter silently broken** — **CLOSED** (PR #4 & PR #5). Correctly imports `MekongMcpServer` and honors `cc_` prefix in handler resolution.
3. **Daemon scheduler = unsandboxed arbitrary shell exec** — **CLOSED** (PR #4). Routed through `CommandSanitizer` strict mode + allowlist.
4. **Masked broken imports** — **CLOSED** (PR #5). Repaired router import, goal engine import, and AGI fail-loud checks.

## Funnel Reachability

All three core business funnels are 100% wired into the live CLI and backed by dedicated services and test suites:

- **Zalo OA** — Fully registered in `src/cli/funnel_commands.py` and mounted in `app_setup.py` as `mekong zalo-oa` (subcommands: `send`, `broadcast`, `followers`, `caption`, `post`). Backed by `integrations.zalo.ZaloOAClient`.
- **Tax & Accounting** — Fully registered in `src/cli/funnel_commands.py` and mounted in `app_setup.py` as `mekong thue` (`tncn`, `tndn`, `gtgt`) and `mekong ke-toan` (`create`, `xml`, `journal`, `summary`). Backed by `src/commands/thue_dnvn.py` and `src/commands/ke_toan.py`.
- **Sophia (AI Video Factory)** — Fully registered in `src/commands/sophia_video.py` and mounted in `tools_app` (`src/cli/tools_browse_collab_commands.py`) as `mekong tools video` (`render`, `create`, `status`, `list`, `avatars`, `voices`, `templates`, `cost`). Backed by `src/services/sophia_video_service.py` with ElevenLabs/D-ID/HeyGen catalogs, Design DNA token styling, MCU credit billing, and deterministic dry-run verification. Also re-exported in `src/cli/funnel_commands.py`.
