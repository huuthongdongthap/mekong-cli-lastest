# Task: LLM Client Wrapping

## Original Request
Wrap `LLMClient` behind the `LLMRouter` Protocol so that the 32 callers of `llm_client.py` can eventually use a unified interface. Currently `LLMRouterAdapter.generate()` is a stub returning `"[stub]"` strings — it must become a real adapter that delegates to `LLMClient`.

## Context
- `src/core/llm_client.py` — `LLMClient` with real production logic (provider failover, caching, hooks, circuit breaker). 32 callers depend on it.
- `src/core/llm_router_adapter.py` — `LLMRouterAdapter` stub implementing `protocols.LLMRouter`. Returns `"[stub]"` strings.
- `src/core/protocols.py` — defines `LLMRouter` Protocol
- `src/core/llm_router.py` — `LLMRouter` class with classify/select_model/estimate_cost (separate from Protocol)
- DUPLICATION_MAP #5 and DEPRECATION_MAP #2 document this as DEFERRED — WRAP NOT REPLACE.

## Goal
- Make `LLMRouterAdapter` a real adapter that delegates `generate()` to `LLMClient`
- Preserve all existing behavior of `LLMClient` (failover, caching, hooks, circuit breaker)
- Do NOT break any of the 32 existing callers
- Add tests proving at least 2 providers can satisfy the same interface
- Keep the public API of `llm_client.py` unchanged

## Constraints
- Do NOT rewrite `LLMClient` — it has real production logic
- Do NOT migrate all 32 callers in this task — just make the adapter work
- Preserve current provider configuration
- All existing tests must continue passing
- Follow YAGNI, KISS, DRY principles
