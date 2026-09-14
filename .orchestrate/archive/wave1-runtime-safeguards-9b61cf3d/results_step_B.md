# Step B Results — Fix MCP Capability Adapter

**Date:** 2026-08-24  
**Status:** PASS

## Files Changed

| File | Lines | Change |
|------|-------|--------|
| `src/core/adapters/mcp_capability_adapter.py` | 157 (was 160) | Bug 1 fix (import), Bug 2 fix (handler prefix strip), docstring update |
| `tests/test_mcp_capability_adapter.py` | 240 (was 219) | Full rewrite: real server discovery, real handler execution, drop all MagicMock server masking |

## Diff Summary

### Adapter (`mcp_capability_adapter.py`)

**Bug 1 — import fix (was line 55):**
- BEFORE: `from src.core.mcp_server import MCPServer` (NameError → silent None → 0 tools)
- AFTER: `from src.core.mcp_server import MekongMcpServer` (module-level, fail-loud)
- `_get_mcp_server()` no longer wraps in try/except; returns `MekongMcpServer()` directly

**Bug 2 — handler prefix strip (was line 85):**
- BEFORE: `handler_name = f"_handle_{tool_name}"` → `_handle_cc_skills_list` → miss (no such method)
- AFTER: `_handler_base()` strips `cc_` prefix; `handler_name = f"_handle_{base}"` → `_handle_skills_list` → hit

**Capability IDs preserved:** `mcp:cc_tasks_list` (consumer-facing id stays `cc_*`)  
**Metadata updated:** `"handler": "_handle_tasks_list"` (stripped in metadata)

### Tests (`test_mcp_capability_adapter.py`)

**Dropped:** All MagicMock server masking (7 tests replaced)  
**Kept:** `_FakeBus` as legitimate bus seam (protocol conformance preserved)  
**Added:** `TestMCPCapabilityAdapterBasics` (6), `TestRealServerDiscovery` (8), `TestRealHandlerExecution` (4), `TestFallbackAndDegradation` (2)

## Verify Commands + Outputs

```bash
# Acceptance 1: Server type
python3 -c "from src.core.adapters.mcp_capability_adapter import MCPCapabilityAdapter as A; a=A(); s=a._get_mcp_server(); print(type(s).__name__)"
# → MekongMcpServer

# Acceptance 2: Real discovery >= 20 tools
python3 -m pytest tests/test_mcp_capability_adapter.py::TestRealServerDiscovery::test_sync_discovers_full_toolset -v
# → PASSED (25 caps = 25 server tools)

# Acceptance 3: Real handler execution
python3 -m pytest tests/test_mcp_capability_adapter.py::TestRealHandlerExecution -v
# → 4 PASSED (skills_list + mcp_list via bus.execute, both ok=True)

# Acceptance 4: Idempotent + fallback
python3 -m pytest tests/test_mcp_capability_adapter.py::TestRealServerDiscovery::test_sync_idempotent \
  tests/test_mcp_capability_adapter.py::TestFallbackAndDegradation -v
# → 3 PASSED

# Acceptance 5: Full targeted test suite
python3 -m pytest tests/test_mcp_capability_adapter.py tests/test_mcp_server.py tests/test_mcp_server_integration.py -q
# → 87 passed

# Ruff
python3 -m ruff check src/core/adapters/mcp_capability_adapter.py tests/test_mcp_capability_adapter.py
# → All checks passed!

# Parity
python3 -m pytest tests/ -q 2>&1 | tail -5
# → 223 failed, 7558 passed, 75 skipped (exact match vs baseline 223)
```

## Acceptance Criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | `_get_mcp_server()` returns `MekongMcpServer` instance | PASS |
| 2 | `sync_from_mcp()` discovers >= 20 tools matching `len(server._tools)` (25) | PASS |
| 3 | `bus.get("mcp:cc_skills_list").execute({})` → `ok=True` (real handler) | PASS |
| 4 | `bus.get("mcp:cc_mcp_list").execute({})` → `ok=True` (real handler) | PASS |
| 5 | `_FakeBus` retained as legitimate bus seam | PASS |
| 6 | Unknown-tool fallback still works | PASS |
| 7 | Idempotent sync (second call returns []) | PASS |
| 8 | Targeted tests all pass (87/87) | PASS |
| 9 | Parity: failed count == 223 (no new failures) | PASS |
| 10 | Ruff clean on modified files | PASS |

## Deviations

None. All changes match plan.md acceptance criteria exactly.

## Protected Flows Verified Untouched

- `src/api/webhooks/router.py` (NOWPayments IPN) — not modified
- `src/raas/nowpayments_router.py` — not modified
- `src/middleware/license_gate.py` — not modified
- `src/core/governance.py` — only Step A changes present (not mine)
