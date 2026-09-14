# Task — Wave 1 Implementation: Fix Critical Defects from Architecture Audit

User authorization: "go" (2026-08-24) following completed audit refresh (PR #3, merged as 7459010db).

## Verbatim intent

Implement Wave 1 of the architecture audit findings (docs/architecture/ARCHITECTURE_ASSESSMENT.md at HEAD 7459010db) — the three critical wiring/safety defects, report-only during the audit, now to be FIXED for real:

1. **Fix `mekong run` production crash** (Defect 1): `src/commands/run.py` `_NullTelemetry` defines only `record_event()` but `src/core/runtime_adapter.py:324,389` calls `self._telemetry.emit(...)` unconditionally → AttributeError at first observe(). Additionally the prod constructor omits `governance=`, `max_cost_usd=`, tracer → approval gate, cost guard, and mission tracing are INERT in prod wiring. Fix the telemetry sink AND wire governance/cost-limit/tracer so the closed-by-code autonomy gates actually engage in the production path.

2. **Fix MCP capability adapter silent failure** (Defect 2): `src/core/adapters/mcp_capability_adapter.py:55` imports nonexistent `MCPServer` (real class is `MekongMcpServer`, src/core/mcp_server.py:165); try/except swallows it → sync_from_mcp discovers ZERO tools. Second bug: handler lookup `_handle_{tool_name}` misses the `cc_` prefix (~line 85). Fix both; un-mask tests that hide this behind MagicMock.

3. **Sandbox daemon scheduler** (Defect 3): `src/daemon/scheduler.py:100` executes entire file content via `executor.run_shell()` with NO sanitizer/allowlist/approval → arbitrary code execution with full user privileges. Add protection consistent with existing patterns (`CommandSanitizer` strict mode used by tool_registry).

## Hard constraints

- DO NOT break protected flows: NOWPayments IPN webhook → tier activation; license gate chain engine/license ↔ src/middleware/license_gate ↔ src/gateway.py
- No new parallel architecture; reuse existing primitives (protocols.py, CommandSanitizer, governance.py, mission_tracer.py)
- Test parity: pytest fail-set must not grow beyond frozen baseline (223 failed / archived at .orchestrate/archive/audit-refresh-7459010db/failed_tests_head_0878f966f.txt); ruff clean
- Real implementations only — no mocks/cheats to pass tests; tests that masked Defect 2 must be fixed to test real behavior
- Known pre-existing CI red on main (pnpm-lock.yaml config debt) is NOT this task's scope

## Deliverable

Working code + real tests + PR merged to main + smoke evidence. Out of scope: defect 4 (masked broken imports), dead-code deletion waves, plan()/delegate() upgrades.
