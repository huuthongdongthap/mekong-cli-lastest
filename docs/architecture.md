# Mekong Architecture — Autonomous Runtime v0.2

> Refreshed: 2026-09-08 · Branch state: `8dcb6f759` (SC8 shipped) · Scope: v0.2 convergence
> ("one verifier, one DAG order" — see
> [IMPLEMENTATION_PLAN.md](./architecture/IMPLEMENTATION_PLAN.md) for the full
> audit-to-action mapping).

Mekong CLI is an open-source autonomous runtime for Solo Companies and Solo
Vibe Coders: one operator delegates goals to AI agents that plan, execute,
verify, repair, and pay for tools — on your own infrastructure.

## Component map (text diagram)

```
 External callers                CLI surface (36 Typer groups via build_app())
 ───────────────                 ─────────────────────────────────────────────
 Buzz / webhook payload ──┐      mekong run --goal "..."  [src/commands/run.py]
                          │                  │
                          ▼                  ▼
        ┌──────────────────────────────────────────────────────────┐
        │            MekongCoreRuntimeImpl                         │
        │            src/core/runtime_adapter.py                   │
        │                                                          │
        │  goal → plan → delegate → execute → observe → verify     │
        │        → repair (≤3) → remember → commit                 │
        │                                                          │
        │  run()           : plain text entry, idempotent mission   │
        │  run_from_payload(): Buzz entry, pre-assigned mission_id │
        │  execute() gates : governance → capability → cost        │
        └───────┬──────────────────┬──────────────────┬─────────────┘
                ▼                  ▼                  ▼
   ┌────────────────────┐ ┌─────────────────┐ ┌──────────────────────┐
   │ CapabilityBus      │ │ Governance      │ │ PaymentProvider       │
   │ InMemory impl;     │ │ ONE decision    │ │ BillingAdapter (MCU), │
   │ BUILTIN/CLI/MCP    │ │ path: risk map  │ │ MockPaymentProvider,  │
   │ sources via        │ │ + audit + loud  │ │ x402-shape codec      │
   │ adapters           │ │ auto-approve    │ │ (mock-only)           │
   └────────────────────┘ └─────────────────┘ └──────────────────────┘
                │                  │                  
                ▼                  ▼                  
   ┌────────────────────┐ ┌─────────────────────────────────────────┐
   │ ToolRegistry / MCP │ │ ExecutionRuntime Protocol               │
   │ adapter            │ │ LocalExecutionRuntime: subprocess +     │
   │ (sync_from_mcp)    │ │ sandboxed fs + sanitizer + timeouts     │
   └────────────────────┘ │ (Cloudflare/Docker = planned, not built)│
                          └─────────────────────────────────────────┘

 Outbound updates: BuzzAdapter.send_update → injectable (url,payload)->int
 transport; silent no-op without callback_url. Core never requires Buzz.
```

## The four buses in one page

| Bus | Doc | Entry class | v0.1 state |
|-----|-----|-------------|------------|
| Lifecycle (core contract) | [core-contract.md](./core-contract.md) | `MekongCoreRuntimeImpl` | Wired; pinned by contract tests |
| Capabilities | [capability-bus.md](./capability-bus.md) | `InMemoryCapabilityBus` | Injected into `mekong run` by default |
| Economic | [economic-bus.md](./economic-bus.md) | `PaymentProvider` protocol | Interface + mock/x402-shape providers |
| Buzz/runtime | [buzz-runtime-adapter.md](./buzz-runtime-adapter.md) | `BuzzRuntimeAdapter` | Versioned `v0.1`, in-process |

Execution isolation is documented in
[runtime-adapters.md](./runtime-adapters.md); the risk/approval model in
[autonomy-model.md](./autonomy-model.md).

## Design rules enforced by tests

1. **One lifecycle engine** — no second goal→commit loop outside
   `runtime_adapter.py` (`tests/test_core_lifecycle_contract.py`).
2. **Provider-neutral core** — no vendor SDK imports in `src/core/`
   (`tests/test_core_boundary.py`; `llm_client.py` is the single documented
   transitional exception).
3. **One policy decision path** — every execution decision flows through
   `Governance.classify_risk` with mandatory audit entries.
4. **No custody** — economic code never touches keys, wallets, or networks.
5. **Buzz-optional core** — buzz import only lazily inside
   `run_from_payload`.

## Runtime behavior (v0.2)

### `verify()` delegates to `RecipeVerifier`

`MekongCoreRuntimeImpl.verify()` (at `src/core/runtime_adapter.py`) now delegates
to the same `RecipeVerifier` the harness (`PEVOrchestrator`, `RecipeOrchestrator`)
uses — collapsing two divergent quality bars into one. Three helpers bridge the gap:

- `_ExecResultLike` — bridges core `Result` (output/error/metadata) to the
  `ExecutionResult`-shaped object `RecipeVerifier.verify()` reads. Mapping:
  `exit_code = 0 if error is None else 1`, `stdout = str(output)`,
  `stderr = error or ""`, `metadata = result.metadata or {}`.
- `_criteria_to_verifier_dict` — maps core `CheckSpec` kinds (`exit_code`,
  `output_pattern`) to the criteria-dict keys `RecipeVerifier` consumes
  (`exit_code`, `output_contains`). Unknown kinds skipped (logged at debug).
- `_report_to_verification` — maps `VerificationReport` back to core
  `Verification`, propagating FAILED/WARNING checks and `report.errors`.

When the criteria-dict is empty, `verify()` falls back to the legacy
`Verification(passed=(result.error is None))` so existing callers are unaffected.

### `_run_goal` executes multi-step plans in topological (DAG) order

`_run_goal` iterates tasks in dependency-respecting order via two helpers:

- `_plan_has_dependencies(plan)` — fast-path check: `any(step.dependencies for
  step in plan.steps)`. Single-step plans (`mekong run` for unknown agents) take
  this fast path, preserving sequential behavior exactly.
- `_topological_task_order(tasks)` — Kahn's algorithm keyed by
  `task.step.id` (string ids like `"task-abc123"` from
  `GoalEngineAdapter._task_to_step`). Raises `RuntimeError` on cycles rather
  than silently mis-ordering.

Note: this does NOT reuse `DAGScheduler` (`src/core/dag_scheduler.py`), which
keys by integer `order` and would silently mismatch against string
`Step.dependencies`. The string-ID-keyed sort mirrors `TaskGraph.ready_tasks()`
semantics (`src/mekongcli/core/goal_engine/models.py`) but operates on core
`Task` objects — no GoalEngine import into core runtime.

## Known limitations (honest list)

- `LLMRouter.stream()` yields one chunk (no native streaming);
  `tool_call()` is still missing from the protocol.
- MemoryStore protocol — 2 conformant implementations (canonical YAML+vector +
  JSONL); the 3-way split is collapsed onto one protocol (`SC7`).
- Network policy in `LocalExecutionRuntime` is a deny-all placeholder struct,
  not an enforcement layer.

Full gap analysis: [architecture/ARCHITECTURE_AFTER_PHASE_2.md](./architecture/ARCHITECTURE_AFTER_PHASE_2.md).
