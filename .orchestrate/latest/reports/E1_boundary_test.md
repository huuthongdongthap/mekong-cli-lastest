# Lane E1 — Core/Adapters Boundary Test (SUPER COMMAND #5, Task 1)

**Branch:** feat/sc5-economic-capability-buses @ 7c5f64093
**Date:** 2026-08-29
**Status:** COMPLETE — 10/10 pass

## Files
- EXTEND `tests/test_core_boundary.py` (219 → 430 lines, +5 tests, 0 src files touched)

## Scout findings (verified at 7c5f64093)
- Core spine (10 files): runtime_adapter, governance, protocols, capability, planner, agent_registry, agent_base, mission_tracer, billing_adapter, agi_loop.
- ZERO imports of `src.core.adapters.*`, `src.core.exec_runtime.*`, `payment_x402*`, `cloudflare`, `docker`, `mcp_server` in spine (grep verified, matches suntzu ROUND-1).
- Confirmed sanctioned seams found by scan:
  - `runtime_adapter.py:325` lazy `src.core.buzz_adapter` inside `run_from_payload` (existing TestBuzzSeam pins it).
  - `planner.py:17` TYPE_CHECKING + `planner.py:378` lazy `src.providers.llm.client` — canonical 622-line LLM client = provider impl (verdict ROUND-1 condition #2 clarified: YES, counts as adapter impl → covered by allowlist + runtime import test).
  - `agi_loop.py:303` lazy `src.providers.llm.client`.
- `src/core/__init__.py` has zero module-level imports (pure lazy `__getattr__`).

## Tests added (class TestAdapterImportNeutrality + TestImportNeutrality)
1. `test_no_adapter_impl_imports_outside_allowlist` — ast.parse every spine file; adapter-impl prefixes (`src.core.adapters.`, buzz, exec_runtime, payment_x402) fail unless file in ADAPTER_IMPORT_ALLOWLIST; relative imports resolved to absolute so `.adapters` cannot dodge the check.
2. `test_allowlisted_spine_seams_are_lazy_not_module_level` — every allowlisted site must be a lazy in-function import, never module level.
3. `test_buzz_imports_confined_to_run_from_payload` — buzz imports across whole spine, only sanctioned runtime_adapter seam.
4. `test_import_core_does_not_pull_provider_modules` — pristine subprocess `import src.core`; asserts sys.modules has none of: src.core.adapters.llm.client, src.core.adapters.payment_x402, src.core.buzz_adapter, src.core.buzz_runtime_adapter, src.core.exec_runtime.cloudflare, src.core.exec_runtime.docker, src.core.mcp_server, src.providers.llm.client.
5. `test_import_all_spine_modules_stays_provider_neutral` — imports all 10 spine modules explicitly, then same assertion.

## Evidence

```
tests/test_core_boundary.py::TestVendorSdkBoundary::test_no_vendor_sdk_imports_anywhere_in_core PASSED
tests/test_core_boundary.py::TestHttpLibAllowlist::test_http_lib_imports_only_in_documented_allowlist PASSED
tests/test_core_boundary.py::TestHttpLibAllowlist::test_allowlist_entries_exist_and_still_import_http_libs PASSED
tests/test_core_boundary.py::TestAdapterImportNeutrality::test_no_adapter_impl_imports_outside_allowlist PASSED
tests/test_core_boundary.py::TestAdapterImportNeutrality::test_allowlisted_spine_seams_are_lazy_not_module_level PASSED
tests/test_core_boundary.py::TestAdapterImportNeutrality::test_buzz_imports_confined_to_run_from_payload PASSED
tests/test_core_boundary.py::TestImportNeutrality::test_import_core_does_not_pull_provider_modules PASSED
tests/test_core_boundary.py::TestImportNeutrality::test_import_all_spine_modules_stays_provider_neutral PASSED
tests/test_core_boundary.py::TestBuzzSeam::test_buzz_import_is_lazy_inside_run_from_payload_only PASSED
tests/test_core_boundary.py::TestBuzzSeam::test_no_buzz_reference_outside_run_from_payload PASSED
======================= 10 passed, 199 warnings in 1.52s =======================
```

## Task 1 acceptance
`python3 -c "import src.core"` → PULLED: NONE, `src.providers` not loaded. Also verified with all 10 spine modules imported. Acceptance MET.

## Notes
- ADAPTER_IMPORT_ALLOWLIST mirrors HTTP_LIB_ALLOWLIST style: every entry documented with reason.
- tests/adapters/ dir untouched (E4/E7 own it).
- Protected paths untouched (byte-unchanged, git status shows only tests/test_core_boundary.py modified).
