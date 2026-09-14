# MEKONG CLI — SUPER COMMAND #8

## Mission

Close architecture gap #4: **Harness Verifier Merge + DAG Scheduler Swap**.

The runtime now has:
- SC6: `plan()` produces 7 role-aware steps with dependency graph via GoalEngineAdapter
- SC7: `remember()` writes through conformant MemoryStore adapter

But the harness verifier (`src/harness/`) is still a separate PEV engine that isn't wired into the core execution loop. The scheduler doesn't consume the DAG structure from GoalEngine. This gap closes by:

1. Merging the harness verifier into the core runtime's execution loop
2. Swapping the scheduler to consume the DAG from GoalEngineAdapter
3. Making `execute()` → `verify()` → `repair()` a real cycle

## Context

- `src/harness/` — PEV engine (plan-execute-verify), agents, observability
- `src/core/runtime_adapter.py` — `MekongCoreRuntimeImpl` with `plan()`/`delegate()`/`execute()`/`remember()`
- `src/core/ports/llm.py` — LLMProviderPort protocol
- `src/core/adapters/` — LLM, MCP, payment, buzz, tool adapters
- `src/mekongcli/core/goal_engine/` — GoalEngine service (multi-step planner)

## Absolute Rules

1. Preserve working functionality — `mekong run`, `cook`, `goal`, `implement` must keep working
2. Do not rewrite the entire repository
3. Do not create a second orchestration framework
4. Do not remove existing business workflows unless proven obsolete
5. Prefer adapters/interfaces over provider-specific logic
6. Keep the core small
7. Every architectural change must have tests
8. No speculative marketplace, tokenomics, custody, or autonomous financial transactions
9. Must not break protected flows (NOWPayments IPN, license gate, payment)
10. Must not touch `.github/workflows/*` (owned by concurrent PR #7)

## Success Criteria

- Harness verifier merged into core runtime execution loop
- Scheduler consumes DAG from GoalEngineAdapter
- `execute()` → `verify()` → `repair()` is a real cycle
- All existing tests pass (parity gate EMPTY for new failures)
- Quality gates green: ruff clean, pyright 0 new errors
