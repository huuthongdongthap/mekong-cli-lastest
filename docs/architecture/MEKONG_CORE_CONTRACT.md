# Mekong Core Contract

> Re-verified: 2026-08-23 · HEAD: 0878f966f

## Non-Negotiable Rules

1. **Provider-neutral core** — Core never imports provider-specific libraries directly. All providers are adapters implementing Protocols.
2. **No vendor lock-in** — Buzz, Cloudflare, Anthropic, OpenAI, x402, MPP are all adapters. None are hard-coded.
3. **Structural typing** — All boundaries use `typing.Protocol` (runtime_checkable). No inheritance required.
4. **Single source of truth** — Each concept has exactly one canonical definition. Duplicates are adapters or wrappers, not independent systems.
5. **Backward compatibility** — Existing commands, APIs, and workflows must not break. Adapters wrap legacy code.
6. **YAGNI + KISS + DRY** — No speculative features. No duplicate systems. Extract shared logic.
7. **Test before commit** — 100% pass rate on new tests. Regression checks on existing tests.

## Canonical Protocols

All line numbers verified against `src/core/protocols.py` (252 lines) at HEAD `0878f966f`.
`AgentDispatcher` is **not** a canonical Protocol — it was removed and has zero importers.

| Protocol | Location | Purpose |
|----------|----------|---------|
| `MekongCoreRuntime` | `protocols.py:123` | 10-step autonomous loop |
| `LLMRouter` | `protocols.py:140` (`stream` at `:147-148`) | Provider-agnostic LLM routing |
| `ToolRegistry` | `protocols.py:153` | Dynamic tool registry |
| `BillingMeter` | `protocols.py:162-168` | MCU billing + settlement |
| `MemoryStore` | `protocols.py:171-178` | Single canonical memory |
| `ObservabilitySink` | `protocols.py:182` | OTel-compatible traces |
| `VerificationEngine` | `protocols.py:190` | Output verification |
| `GoalEngine` | `protocols.py:198` | Goal decomposition + replanning |
| `PaymentProvider` | `protocols.py:206-212` | Payment abstraction |
| `CapabilityBus` | `capability.py` (re-exported at `protocols.py:16`) | Capability abstraction |
| `SerializableBillingResult` | `protocols.py:216` | Billing result serialization contract |

## Canonical Implementations

| Protocol | Implementation | Status |
|----------|---------------|--------|
| `MekongCoreRuntime` | `MekongCoreRuntimeImpl` (runtime_adapter.py) | ✅ Phase 2 |
| `LLMRouter` | `LLMRouterAdapter` (llm_router_adapter.py) | ✅ Phase 2 |
| `CapabilityBus` | `InMemoryCapabilityBus` (capability.py) — unwired in production | ✅ Phase 2 |
| `PaymentProvider` | ZERO concrete conformants (`BillingAdapter` delegates to stub) | ❌ Missing |
| `MemoryStore` | ZERO exact conformers (contract aspirational) | ❌ Missing |
| `ToolRegistry` | `ToolRegistry` (tool_registry.py) builtins; `MCPCapabilityAdapter` BROKEN | 🔄 Partial |
| `VerificationEngine` | `Verifier` (verifier.py) | 🔄 Basic |
| `ObservabilitySink` | `TelemetryCollector` (telemetry_collector.py) | 🔄 Basic |
| `GoalEngine` | `GoalEngine` (src/mekongcli/core/goal_engine/) | ✅ Implemented (non-conformant) |

**Implementation notes (verified at HEAD):**

- **GoalEngine is IMPLEMENTED NOW** — `src/mekongcli/core/goal_engine/`
  contains `models.py`, `planner.py`, `service.py`, `store.py` with
  `SQLiteGoalStore`. However, the service does **not** conform to the
  `protocols.GoalEngine` signature (`decompose`/`adapt`/`commit`) — no such
  methods were found on the service class. Treat it as a parallel
  implementation, not a Protocol conformant.
- **Capability adapters (filesystem/shell/browser/Cloudflare) are still
  MISSING** as protocol-conformant adapters. `tool_registry` builtins exist but
  do not implement the `CapabilityBus` protocol, and `InMemoryCapabilityBus`
  is unwired in production (optional param on `runtime_adapter`, never
  instantiated).
- **x402/MPP `settle_payment` is STILL STUB** — `mcu_billing.py:318-345`
  returns `pending=True` ("x402/MPP not yet implemented"). `PaymentProvider`
  has ZERO concrete conformants; `BillingAdapter` delegates `settle_payment`
  to the stub. NOWPayments is hard-coded and bypasses the protocol entirely
  (`gateway.py:34,109`).
- **MCP:** server side is functional (25 tools via FastMCP stdio/SSE,
  `python -m src.core.mcp_server`). The client/consumer side is MISSING
  entirely — the core cannot consume external MCP servers.
- **MemoryStore contract is aspirational** — ZERO exact conformers. The
  canonical store exposes `query()` not `search()`; the bridge exposes
  `record`/`search`/`recall`/`recent`/`delete`, neither matching the Protocol's
  `store`/`retrieve`/`delete`/`search` shape.
- **Runtime loop stages honesty:** `execute`/`observe`/`verify`/`repair`/
  `remember`/`commit` are REAL. `plan()` is a single-step stub
  (`runtime_adapter.py:232-234`). `delegate()` is a single-agent stub
  (`runtime_adapter.py:236-238`). The prod dispatcher `_NullDispatcher`
  (`run.py:47-51`) raises `NotImplementedError`.

## Known Defects (verified at HEAD)

1. **MCP capability adapter silently broken.** `mcp_capability_adapter.py:55`
   imports nonexistent `MCPServer` — the real class is `MekongMcpServer`
   (`mcp_server.py:165`). The `try/except` swallows the `ImportError`, so
   `sync_from_mcp` silently discovers ZERO tools. A second bug: the handler
   lookup `_handle_{tool_name}` misses the `cc_` prefix. Tests mask both with
   `MagicMock`.
2. **`mekong run` production path broken.** `_NullTelemetry` (`run.py:54-58`)
   lacks `emit()`, but the runtime calls `self._telemetry.emit(...)`
   unconditionally (`runtime_adapter.py:324,389`) → `AttributeError` at first
   `observe()`. Prod wiring also omits `governance=`, `max_cost_usd=`, and a
   tracer. See `docs/architecture/AUTONOMY_GAPS.md` → NEW WIRING DEFECTS.

## Provider Adapters

### LLM Providers
| Provider | Adapter File | Status |
|----------|-------------|--------|
| Claude (Anthropic) | Via `llm_client.py` | ✅ |
| OpenAI | Via `llm_client.py` | ✅ |
| Qwen | Via `llm_router_adapter.py` | 🔄 Router supports |
| DeepSeek | Via `llm_router_adapter.py` | 🔄 Router supports |
| Local models | Via `llm_router_adapter.py` | 🔄 Router supports |

### Capability Providers
| Provider | Adapter File | Status |
|----------|-------------|--------|
| MCP | `mcp_capability_adapter.py` | ❌ BROKEN (imports nonexistent `MCPServer`) |
| Filesystem | Not yet | ❌ Missing |
| Shell | Not yet | ❌ Missing |
| Browser | Not yet | ❌ Missing |
| Cloudflare | Not yet | ❌ Missing |

### Economic Providers
| Provider | Adapter File | Status |
|----------|-------------|--------|
| x402 | Stub in `mcu_billing.py` | 🔄 Stub (pending=True) |
| MPP | Stub in `mcu_billing.py` | 🔄 Stub (pending=True) |
| NOWPayments | `raas/nowpayments_*.py` | ✅ (bypasses PaymentProvider protocol) |

## Invariants

1. **Core imports only from `protocols.py`** — Core modules import Protocol types from `protocols.py` only. Never import adapter implementations.
2. **Adapters import from core** — Adapters import Protocol types and implement them.
3. **No circular imports** — `protocols.py` is the leaf. No module imports `protocols.py` from within `protocols.py`.
4. **Protocols are structural** — No `@runtime_checkable` enforcement on core boundaries (kept for test convenience only).
5. **Adapters are thin** — An adapter should be <200 lines. If it's bigger, split it.
6. **Tests mirror structure** — Each Protocol has a `test_protocol_compliance.py` test. Each adapter has a `test_*_adapter.py` test.

## Anti-Patterns (Forbidden)

| Anti-Pattern | Why Forbidden | Example |
|--------------|---------------|---------|
| Core imports adapter | Breaks provider-neutral guarantee | `from src.core.llm_client import ...` in `runtime_adapter.py` |
| Hard-coded provider | Vendor lock-in | `import anthropic` in core |
| Duplicate registry | Confusion about source of truth | `DEFAULT_PROMPTS` + `.mekong/agents/*.md` |
| Binary classification | Insufficient for autonomy | `Governance.classify()` with 3 outcomes only |
| Infinite retry | Resource exhaustion | `repair()` with no limit |
| Dict-based memory | No isolation, no TTL | `MemoryStore` basic dict |
