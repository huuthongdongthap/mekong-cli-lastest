# DEPRECATION.md

Tracking file for deprecated and removed modules. Each entry states why the
module was removed, how to migrate, and which test pins the migration.

## Removed: `src/harness/pev/planner.py`

- **Removed:** 2026-08-26
- **Reason:** Byte-identical duplicate of `src/core/planner.py` (verified with
  `cmp`, exit 0 immediately before deletion). Zero behavioral difference.
- **Migration:** Import from `src.core.planner` instead:

  ```python
  # Before
  from src.harness.pev.planner import PlanningContext, RecipePlanner

  # After
  from src.core.planner import PlanningContext, RecipePlanner
  ```

  Package-level re-exports (`from src.harness.pev import RecipePlanner, ...`)
  are unchanged and now resolve to `src.core.planner`.
- **Replacement test:** `tests/test_pev_planner_converged.py` — asserts the
  module is gone and that PEV orchestrator symbols resolve to canonical
  `src.core.planner` identities.

## Moved: `src/core/llm_client.py` → `src/providers/llm/client.py` (RESOLVED)

- **First moved:** 2026-08-27 to `src/core/adapters/llm/client.py` (transitional).
- **Final move:** 2026-08-27 to `src/providers/llm/client.py` — transitional
  exception closed. The LLM client is a provider adapter, not core orchestration
  logic, and now lives outside `src/core/` entirely. The
  `src/core/adapters/llm/` directory and its boundary-test allowlist entry are
  removed.
- **Migration:** Import from the canonical path:

  ```python
  # Before (transitional)
  from src.core.adapters.llm.client import LLMClient, get_client

  # After (canonical)
  from src.providers.llm.client import LLMClient, get_client
  ```

  No shim — all references repointed in one scripted pass.

## Resolved historical (from `docs/architecture/DUPLICATION_MAP.md`)

The duplication audit in `docs/architecture/DUPLICATION_MAP.md` flagged
`src/harness/pev/planner.py` vs `src/core/planner.py` as BYTE-IDENTICAL with
the recommendation to delete the harness-local copy. That recommendation is
now resolved by this removal. The same map defers the harness verifier's
`explain()`/quality-gate merge into `src/core/verifier.py` — that remains
deferred, not part of this deprecation.
