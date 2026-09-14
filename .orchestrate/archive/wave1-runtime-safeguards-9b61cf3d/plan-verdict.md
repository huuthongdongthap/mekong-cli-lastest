PASS ROUND: 1

# Plan Verdict — Wave 1: Fix Critical Defects from Architecture Audit

Evaluator: suntzu · Date: 2026-08-24 · Plan: `.orchestrate/latest/plan.md` · Base: main @ 7459010db (verified: `git rev-parse HEAD` = 7459010db773e9851f21f158d77a3fb79c77e818)

## Verdict

**PASS** — Plan gate cleared. All 6 verification conditions satisfied with direct code evidence at HEAD. No blocking findings. Proceed to execution (Bước A → B → C tuần tự).

## Evidence (what was actually checked)

Files read: plan.md, task.md, src/commands/run.py, src/core/telemetry_sink_adapter.py, src/core/runtime_adapter.py (100-220, 320-330), src/core/adapters/mcp_capability_adapter.py (full), src/core/governance.py (60-145), src/core/mcp_server.py (grep + 195-210), src/core/tool_registry.py (270-295), src/core/command_sanitizer.py (grep), src/daemon/scheduler.py (90-115 + imports), src/daemon/dlq.py:30, src/core/llm_router_adapter.py (80-95), src/core/protocols.py (178-190), src/core/mission_tracer.py (grep).

Commands run:
- `git rev-parse HEAD` → 7459010db (matches plan base)
- `wc -l .orchestrate/archive/audit-refresh-7459010db/failed_tests_head_0878f966f.txt` → 223 lines (baseline matches plan claim)
- `python3 -c "import mcp; from src.core.mcp_server import MekongMcpServer; ..."` → `tools: 25` (SDK present, create_app works, 25 cc_* tools — plan's "≥20 caps" and "25 tool cc_*" claims correct)
- `python3 -c "from src.core.governance import Governance; ..."` → `deploy: REVIEW_REQUIRED | rm -rf: FORBIDDEN | hello: SAFE` (plan's test goal strings classify exactly as the acceptance criteria expect)
- `ls` on all 7 referenced existing test files → all exist

## Condition verification

### 1. File-level checklist with acceptance criteria (A/B/C) — SATISFIED
Plan §2: each bước lists exact files (A: src/commands/run.py + tests/test_run_command_wiring.py; B: src/core/adapters/mcp_capability_adapter.py + tests/test_mcp_capability_adapter.py; C: src/daemon/scheduler.py [+ optional sandbox.py if >200 LOC] + tests/test_daemon_scheduler.py), numbered precise changes, and checkable acceptance criteria (grep counts, python one-liners with expected stdout, specific test assertions, verify commands).

### 2. Technical decisions match real code at HEAD — SATISFIED (all 5 spot-checks)
- **(a) TelemetrySinkAdapter**: exists at src/core/telemetry_sink_adapter.py with `emit()` (:23) + `flush()` (:56); `ObservabilitySink` Protocol at protocols.py:182-186 defines exactly emit+flush and IS `@runtime_checkable` (:181) — plan's isinstance acceptance criterion is valid. Adapter maps `task_completed` (runtime_adapter.py:324-329 emits it) and `run_completed` (:389) — both event types the runtime actually emits are covered.
- **(b) Constructor signature**: runtime_adapter.py:120 — `governance=None` and `max_cost_usd: float | None = None` kwargs EXIST; NO `tracer` kwarg. Plan's correction of the audit doc ("tracer phải qua start_mission") is RIGHT: `start_mission(goal, tracer=None, mission_id=None)` at :155 is the only tracer injection point; plain `run()` (:185) never calls start_mission so `_mission_id=None` → trace no-ops, exactly as plan states.
- **(c) MekongMcpServer**: mcp_server.py:165 confirmed. Import bug confirmed real: adapter :55 imports `MCPServer` (nonexistent), try/except :58-60 swallows → returns None → zero tools. Handler mismatch confirmed real: tools registered as `cc_*` (mcp_server.py:247+, 25 defs) but handlers are `_handle_*` WITHOUT prefix (:459+); adapter :85 builds `_handle_{tool_name}` → always misses. Plan's strip-prefix fix (`base = tool_name[3:]`) is correct.
- **(d) CommandSanitizer + tool_registry strict pattern**: tool_registry.py:274-289 confirmed verbatim (comment :274, `CommandSanitizer(strict_mode=True)` :279, fail-closed ImportError branch :287-290). CommandSanitizer has `strict_mode` param (:105), `blocked_reason` field (:32), `_CHAINING_RE = re.compile(r"[;&|]|\n")` (:304) — plan's "mọi file đa dòng bị chặn" claim correct; SUSPICIOUS_PATTERNS includes base64 -d (:87). `DeadLetterQueue.move_to_dlq(filepath, reason)` exists at daemon/dlq.py:30; scheduler already holds `self.dlq` (scheduler.py:56) and raw exec confirmed at :100.
- **(e) GOVERNANCE_AUTO_APPROVE**: governance.py:124 confirmed; bypass logic :122-137 matches plan's SAFE/REVIEW/FORBIDDEN semantics. Supporting claims also verified: `LLMRouterAdapter.estimate_cost` returns dict with `cost_usd` (llm_router_adapter.py:86-93) and `_check_cost_guard` reads `cost_estimate.get("cost_usd")` (runtime_adapter.py:420) — cost guard will genuinely engage; error strings "Action requires human approval" (:275), "Action forbidden" (:266), "Cost ceiling exceeded" (:426) match plan's test assertions.

### 3. Protected flows — SATISFIED
Plan §3 explicitly freezes NOWPayments IPN chain (src/api/webhooks/router.py, src/raas/nowpayments_router.py) and license gate chain (engine/license ↔ src/lib/raas_gate/__init__.py ↔ src/middleware/license_gate.py ↔ src/gateway.py) with escalate-on-touch rule. All 6 protected paths verified to exist. Files touched by plan (run.py, mcp_capability_adapter.py, scheduler.py, 3 test files) have zero overlap with protected set.

### 4. Test strategy real, parity gate clear — SATISFIED
Gate 4 (§3) explicitly forbids MagicMock masking import/handler lookup; Step B requires REAL server discovery (assert len(caps) ≥ 20 vs server._tools) and REAL handler execution (`bus.get("mcp:cc_skills_list").execute({})` → ok=True, ≥2 tools); keeps `_FakeBus` as legitimate bus seam (conformance tested elsewhere) — correct discrimination. Step A requires end-to-end run through the actual old crash path (observe/emit). Parity gate: 223-failed baseline frozen at archived file (verified 223 lines), new failures = FAIL, baseline-red tests turning green counted as improvement with PR note — matches task constraint.

### 5. Ship plan complete — SATISFIED
§5: branch feat/wave1-defect-fixes from 7459010db; no .orchestrate/ staging; 3 conventional commits (no plan/defect codes in messages — complies with stable-artifacts rule); PR with breaking-change note (governance ON) + parity evidence + smoke output; CI escrow logic correct (pnpm-lock.yaml red = pre-existing, cite not fix — matches task hard constraint); squash merge gated on parity PASS; 3 post-merge smoke commands; explicit NO deploy.

### 6. Scope discipline — SATISFIED
Only 3 defects addressed. §5.7 explicitly preserves out-of-scope: defect 4 masked imports, dead-code waves, plan()/delegate() upgrades. Step C item 5 keeps PostGate verify_commands untouched. No new parallel architecture — reuses TelemetrySinkAdapter, Governance, MissionTracer, CommandSanitizer, DeadLetterQueue (all verified existing), per task constraint.

## Findings

None blocking.

## Out-of-scope observations (KHÔNG chặn pipeline — tham khảo cho execution/PR)

1. **LOW — Bước A item 5 (optional `return True` in `Governance.request_approval`)**: verified the fall-through is a dead path today (runtime_adapter.py:270 only calls it in the REVIEW_REQUIRED branch), so the 1-line hardening is safe and correctly marked optional. Executor may include or skip; if included, mention in PR as defensive hardening, not defect fix.
2. **LOW — Step B acceptance `len(caps) >= 20`**: actual count is 25 (verified live). Margin is fine, but the companion assertion should compare against `len(server.create_app()._tools)` dynamically (plan already says so) rather than hardcoding 25, to survive future tool additions.
3. **LOW — Cost-guard test path**: `_check_cost_guard` fires from `meta.get("estimated_cost")` (runtime_adapter.py:293); with `_NullDispatcher` the estimate must come from the llm_router default path. Plan's shape claim is verified; executor should confirm the estimate actually reaches meta in the no-dispatcher path when writing the `max_cost_usd=0.0000001` test.
4. **LOW — Working tree state**: `git status` shows .orchestrate/latest deletions/modifications untracked-ish (execution.md, plan-verdict.md, result-verdict.md, ship-report.md deleted; archive/ untracked). Plan §5.1 already says do NOT stage .orchestrate/ — executor must honor this.

## Scope check

Plan touches only: src/commands/run.py, src/core/adapters/mcp_capability_adapter.py, src/daemon/scheduler.py (+ optional src/daemon/sandbox.py), tests/test_run_command_wiring.py (new), tests/test_mcp_capability_adapter.py, tests/test_daemon_scheduler.py. Zero overlap with protected flows. No out-of-scope files.

## Conditions

None — verdict is PASS. Execution may proceed Bước A → B → C, each gated by §3 gates (target pytest xanh, ruff sạch, parity ≤223 no-new-fail, no mock-che).
