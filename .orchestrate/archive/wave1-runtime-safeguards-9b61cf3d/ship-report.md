# Ship Report — Wave 1 Runtime Safeguards

## Summary

Wave 1 critical defect fixes shipped via PR #4.

- PR: https://github.com/minhlongs/mekong-cli/pull/4
- Branch: feat/wave1-defect-fixes
- Commit on branch: 8213e9b05
- Squash merge SHA: 9b61cf3d7d5aecf7670c3b651b49bebe34fb9ed9
- Result gate: CONDITIONAL PASS Round 1; only MED condition was full-suite parity pending at evaluator runtime, later confirmed exact (223 failed baseline match)
- Deploy: none (CLI/library repo; task requested no deploy)

## Code shipped

1. `mekong run` production wiring:
   - Replaced crash-prone null telemetry with `TelemetrySinkAdapter`
   - Wired `Governance`, cost ceiling, and `MissionTracer`
   - Preserved existing escape hatch (`GOVERNANCE_AUTO_APPROVE`) and added default cost ceiling behavior
   - Prevented repair loop from masking gate-blocked errors

2. MCP capability adapter:
   - Imports real `MekongMcpServer`
   - Fails loudly on missing import instead of silently discovering zero tools
   - Resolves public `cc_*` tools to prefix-stripped internal handlers
   - Keeps public capability IDs stable as `mcp:cc_*`

3. Daemon scheduler sandbox:
   - Uses `CommandSanitizer(strict_mode=True)`
   - Enforces conservative first-token allowlist
   - Sends unsafe missions to DLQ with reason and journal record
   - Rejects symlinked mission files before read

## Verification

- `python3 -m pytest tests/test_run_command_wiring.py -q` → 18 passed
- `python3 -m pytest tests/test_mcp_capability_adapter.py -q` → 20 passed
- `python3 -m pytest tests/test_daemon_scheduler.py -q` → 48 passed
- Combined post-merge targeted suite → 86 passed
- Full parity: `python3 -m pytest tests/ -v --tb=no` → 223 failed, 7569 passed, 75 skipped
  - Baseline: 223 failed, 7533 passed, 75 skipped
  - Delta: +0 failed, +36 passed, +0 skipped
- `python3 -m ruff check src/ tests/` → All checks passed
- Post-merge import smoke → `SMOKE_OK runtime_wiring mcp_server sanitizer`

## Protected flows

Untouched:

- NOWPayments IPN webhook chain
- `engine/license/`
- `src/middleware/license_gate.py`
- `src/gateway.py`
- `src/lib/raas_gate/`

## CI status

Post-merge GitHub Actions produced the known pre-existing failure class:

- `CI` failed at Node setup because `pnpm-lock.yaml` is missing.
- Multiple related workflows failed for the same repository config/infra debt.
- `Security Hardening & Attestation` succeeded.

This matches the task's explicit escrow: known pre-existing CI red on main (`pnpm-lock.yaml` config debt) is out of scope for Wave 1.

## Smoke

Corrected post-merge smoke verified:

- `_build_runtime(max_cost_usd=1.0)` wires `Governance`, `TelemetrySinkAdapter`, and cost ceiling
- `MekongMcpServer().create_app()` exposes 25 tools
- `CommandSanitizer(strict_mode=True).sanitize("echo hello")` returns safe

## Escrow / follow-up

1. LOW — External code-reviewer security pass was rejected by provider filter. Coverage retained via Step C self-review, suntzu gate, and security tests.
2. LOW — Broader main CI infra/config debt remains: missing `pnpm-lock.yaml` and related workflow drift.
3. LOW — Pre-existing `test_autonomous_loop.py::test_full_loop_returns_result` red remains in frozen 223-fail baseline.

## Verdict

GREEN for Wave 1 scope: PR merged, parity preserved, targeted tests green, ruff clean, protected flows untouched.
