# Core Contract — MekongCoreRuntime Lifecycle (v0.1)

Canonical lifecycle of `src/core/runtime_adapter.py:MekongCoreRuntimeImpl`. All stage names and method mappings are pinned by `tests/test_core_lifecycle_contract.py`.

## Stage ↔ Method Mapping

| Stage | Method | Description |
|-------|--------|-------------|
| GOAL | `goal()` | Create a `Goal` dataclass embedding a `Context` (CONTEXT stage folded in) |
| PLAN | `plan()` | Produce a single-step `Plan` from the goal intent |
| DELEGATE | `delegate()` | Map each plan step to a `Task` with the default agent |
| EXECUTE | `execute()` | Run task via tool registry / dispatcher; governance + cost gates |
| OBSERVE | `observe()` | Emit telemetry; attach estimated cost; build `Observation` |
| VERIFY | `verify()` | Check criteria (`exit_code` default) → `Verification` |
| REPAIR | `repair()` | Strategy: RETRY / FALLBACK / ESCALATE / ROLLBACK; cap `_MAX_REPAIR_ATTEMPTS = 3` |
| REMEMBER | `remember()` | Store observation in session-tier memory (`MemorySeparation.store`) |
| COMMIT | `commit()` | Record usage + quota check; final telemetry; return `CommitRecord` |

## Entry Points

### `run(goal_text: str) -> Result`
Plain goal string entry. **Idempotent mission trace**:
- Starts a mission **only when `self._mission_id is None`**.
- CLI wiring (`src/commands/run.py`) calls `start_mission()` before `run()` so every step lands on the tracer-created mission.
- `_finish_mission()` intentionally **does not reset `_mission_id`** — callers may still correlate after the loop. A second `run()` on the same instance continues under the active mission until the caller starts a new one.

### `run_from_payload(payload: dict) -> Result`
External payload entry (e.g., Buzz webhook). **Bypasses `run()` entirely**:
- Calls `_run_goal()` directly with a pre-assigned `mission_id` from payload.
- Never re-enters `run()`, so the guard in `run()` cannot double-fire on this path.
- Buzz import is **lazy inside this function only** — no module-level buzz coupling in core.

### `_run_goal(goal: Goal, start: float) -> Result`
Shared internal loop executing the 10 stages in order. Returns merged `Result`.

## Protocol Surface (`src/core/protocols.py`)

Structural Protocols the runtime and its adapters satisfy. All are
`@runtime_checkable` unless noted.

| Protocol | Methods | Canonical conformant implementation |
|----------|---------|-------------------------------------|
| `MekongCoreRuntime` | `run / goal / context / plan / delegate / execute / observe / verify / repair / remember / commit` | `MekongCoreRuntimeImpl` (`runtime_adapter.py`) |
| `LLMRouter` | `classify / select_model / estimate_cost / generate / stream / structured_output / tool_call / health` | `llm_router_adapter` (wraps `src/core/adapters/llm/client.py`; `tool_call()` added in v0.2) |
| `ToolRegistry` | `register / execute / list_tools / list_mcp_tools` | `src/core/tool_registry.py` |
| `BillingMeter` | `record_usage / check_quota / settle_payment` | `MCUBilling` (settle remains a stub) |
| `PaymentProvider` | legacy 3 + `quote / request_payment / verify / refund` | `BillingAdapter`, `MockPaymentProvider`; x402-shape codec is data-only |
| `MemoryStore` | `store / retrieve / delete / search` | `MemoryStoreConformant` (`src/core/adapters/memory_store_conformant.py`) — wraps `memory_canonical.MemoryStore`; `store`→`record` (bytes as base64 in context, TTL via `expires_at`), `retrieve`→`query` exact-goal match, `delete`→filter `_entries` + persist, `search`→`semantic_search` with substring fallback mapped to `MemoryHit` |
| `GoalEngine` | `decompose / adapt / commit` | `GoalEngineAdapter` (`src/core/adapters/goal_engine_adapter.py`) — wraps the live engine in `src/mekongcli/core/goal_engine/service.py`; `decompose`→`create_goal`, `adapt`→replan via new goal with failure context, `commit`→`run_goal` |
| `VerificationEngine` | `verify / explain` | harness verifier (merge deferred) |
| `ExecutionRuntime` | `execute / filesystem / process / network_policy / environment / preview / health / destroy` | `LocalExecutionRuntime` (`src/core/exec_runtime/local.py`) |

Dataclasses `Quote`, `PaymentRequest`, `PaymentReceipt` carry pure payment
data — never secrets.

## Invariants

1. **Single canonical lifecycle** — No second engine (PEV/harness) duplicates `goal→…→commit`.
2. **Provider-neutral core** — `src/core/` imports **no vendor SDK** (`anthropic`, `openai`). Provider access routes through `llm_router_adapter` → `llm_client` (transitional exception, documented in `tests/test_core_boundary.py`).
3. **HTTP-lib allowlist** — Generic `requests`/`httpx` only in documented internal gateway/service clients (see allowlist in `tests/test_core_boundary.py`).
4. **Repair cap** — Hard limit of 3 attempts enforced by `_MAX_REPAIR_ATTEMPTS` and `_repair_count` gate inside `execute()`.
5. **Mission trace correlation** — All telemetry and tracer calls carry `mission_id`; `run()` and `run_from_payload()` both produce complete start/step/finish traces.
6. **Cost ceiling** — Per-mission hard ceiling via `max_cost_usd` constructor arg; enforced in `execute()` before tool call.

## Exceptions Documented

| Exception | File | Status | Resolution Target |
|-----------|------|--------|-------------------|
| `llm_client.py` imports `requests` (OpenRouter HTTP) | `src/core/llm_client.py` | Transitional — wrapped by `llm_router_adapter` | MOVE to `src/providers/` (deferred) |
| Buzz lazy import in `run_from_payload` | `src/core/runtime_adapter.py:219` | Sanctioned seam — core runs without Buzz | Stable interface for v0.1 |
| HTTP libs in 19 allowlisted modules | `tests/test_core_boundary.py` | Documented internal clients | No action; allowlist is the contract |

## Testing Contract

| Test File | Purpose |
|-----------|---------|
| `tests/test_core_lifecycle_contract.py` | Stage order, method mapping, repair cap, mission trace idempotency, payload path regression |
| `tests/test_core_boundary.py` | Provider-neutral gate (no anthropic/openai), HTTP-lib allowlist enforcement, Buzz seam pinning |

Both must pass on every commit.

---

*Full architecture docs in `docs/architecture.md` (E7). This contract is the minimal pinned surface for v0.1.*