## Summary

Fixes the three critical Wave 1 defects from the architecture audit:

- Wire production `mekong run` through `TelemetrySinkAdapter`, `Governance`, cost ceiling, and `MissionTracer` so runtime safeguards engage instead of crashing or staying inert.
- Fix MCP capability adapter discovery by importing real `MekongMcpServer` and resolving `cc_*` tools to prefix-stripped handlers while keeping public capability IDs stable.
- Protect daemon scheduler mission execution with `CommandSanitizer(strict_mode=True)`, an allowlist, DLQ quarantine on violations, and symlink rejection.

## Verification

- `python3 -m pytest tests/test_run_command_wiring.py -q` → 18 passed
- `python3 -m pytest tests/test_mcp_capability_adapter.py -q` → 20 passed
- `python3 -m pytest tests/test_daemon_scheduler.py -q` → 48 passed
- `python3 -m pytest tests/ -v --tb=no` → 223 failed, 7569 passed, 75 skipped (exact failure-count parity with frozen baseline; +36 passes, 0 new failures)
- `python3 -m ruff check src/ tests/` → All checks passed

## Scope / protected flows

Protected flows were not touched:

- NOWPayments IPN webhook chain
- license gate chain (`engine/license` ↔ `src/middleware/license_gate.py` ↔ `src/gateway.py`)

Known CI debt on main (`pnpm-lock.yaml` config debt) remains out of scope for this Wave 1 fix.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
