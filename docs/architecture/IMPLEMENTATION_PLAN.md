# Implementation Plan — Audit-to-Runtime Mapping

> Refreshed: 2026-08-26 · Base: `d6138541a7` · HEAD: `ada77e6b41`
>
> This table maps audit findings to concrete actions taken in Autonomous
> Runtime v0.1 (`feat/autonomous-runtime-v01`). It is copied verbatim from
> pipeline plan §2 (`.orchestrate/latest/plan.md`) with two corrections
> applied to row 14: the HTTP library is `requests` (generic HTTP +
> OpenRouter endpoint), NOT a vendor SDK; reference count updated to
> 46 file references.
>
> Status column reflects state after v0.1 lanes E0–E6 landed.

| # | Audit Finding (source) | Existing Files (verified) | Action | Reason | Risk | Status |
|---|---|---|---|---|---|---|
| 1 | Lifecycle 10 stage real nhưng plain `run()` không start mission → trace/telemetry `mission_id=None` (AUTONOMY_GAPS #4/#10 caveat) | `src/core/runtime_adapter.py:155,185-191,214-228` | **REFACTOR** — `run()` gọi `start_mission(goal_text)`; contract docs chuẩn hóa tên stage | §3/§15: một canonical lifecycle, observability gắn mission | LOW | DONE (E1) |
| 2 | `plan()`/`delegate()` stub 1 bước | `src/core/runtime_adapter.py:232-238` | **KEEP** + docs ghi limitation | §23 STOP: real planner là Phase sau (effort L) | MED (documented) | KEPT |
| 3 | GoalEngine implemented nhưng non-conformant Protocol | `src/mekongcli/core/goal_engine/service.py` (create_goal/run_goal/…) | **KEEP** (defer conform) | Live consumers (cook/goal/implement); không phá khi chưa cần | MED | KEPT (deferred) |
| 4 | CapabilityBus + `InMemoryCapabilityBus` có sẵn, well-tested, NHƯNG 0 wiring prod | `src/core/capability.py:90-141`; `src/commands/run.py`; `src/core/tool_registry.py:114-235` | **WRAP+WIRE** — NEW `src/core/adapters/tool_capability_adapter.py`; inject bus vào `run.py` | §7: capability bus là xương sống; nền đã có, chỉ nối | LOW-MED | DONE (E2) |
| 5 | MCP capability adapter đã fix Wave 1, real-server tests ≥20 tools | `src/core/adapters/mcp_capability_adapter.py`; `tests/test_mcp_capability_adapter.py` | **KEEP + TEST** (thêm e2e sync→bus.execute) | §8: MCP-as-adapter đã có nền; client-side defer | LOW | DONE (E2) |
| 6 | Governance 3 lớp SAFE/REVIEW_REQUIRED/FORBIDDEN; thiếu mapping risk 4 mức; `GOVERNANCE_AUTO_APPROVE` bypass im lặng | `src/core/governance.py:28-134` | **REFACTOR** — mở rộng cùng class (classify_capability, audit-always, bypass phải loud) | §13: MỘT đường quyết định, không hệ permission thứ 2 | MED | DONE (E3) |
| 7 | `settle_payment` stub; `PaymentProvider` 0 conformant; NOWPayments mount thẳng (PROTECTED) | `src/core/protocols.py:206-212`; `src/core/billing_adapter.py`; `src/core/mcu_billing.py:318-345`; `src/gateway.py:34,109` (đừng đụng) | **NEW** `src/core/adapters/payment_mock.py` + `payment_x402_shape.py` (interface-conformant, mock-only); **REFACTOR** protocol + BillingAdapter | §12: economic-ready = interface + tests, không custody/key | MED | DONE (E4) |
| 8 | Buzz `receive_goal` ok; `send_update` không transport; chưa có versioned runtime interface | `src/core/buzz_adapter.py:26-67`; `src/core/runtime_adapter.py:191-212` | **REFACTOR** send_update (injectable transport, no-op không callback) + **NEW** `src/core/buzz_runtime_adapter.py` (iface §11) | §11: Buzz-compatible, core chạy được không cần Buzz | LOW | DONE (E5) |
| 9 | Chưa có Runtime abstraction local-first | NEW `src/core/exec_runtime/` (Protocol + LocalExecutionRuntime) reuse `src/core/command_sanitizer.py` | **NEW** | §9/§10 foundation: execute/fs/network_policy/health/destroy | MED | DONE (E5) |
| 10 | PEV planner byte-identical core planner (cmp exit 0) | `src/harness/pev/planner.py` ↔ `src/core/planner.py` | **DELETE** + repoint importers + DEPRECATION note | DUPLICATION_MAP #5; audit-identified duy nhất đủ an toàn tuyệt đối | LOW | DONE (E6) |
| 11 | Harness verifier near-dup (+explain/quality gates); DAG stub che scheduler thật | `src/harness/pev/verifier.py`; `src/harness/pev/dag_scheduler.py` (19 dòng stub) | **KEEP** (defer merge/swap) | Swap mù có thể đổi behavior `mekong swarm`; cần lane riêng | MED | KEPT (deferred) |
| 12 | Memory 3-way split, Protocol 0 conformant | `src/core/memory_canonical.py` (~20 consumers); `memory_store.py` (JSONL); `protocols.py:171-178` | **DEFER** (docs ghi gap) | Không block foundation; cả 2 store live; design_intelligence cố tình bind JSONL | MED | DEFERRED |
| 13 | `AgentMeta` thiếu declarative autonomy fields | `src/core/agent_registry.py:24-30` | **REFACTOR** — thêm `risk_level/model_preference/max_budget/max_iterations/approval_policy` + defaults, backward-compat | §6 tối thiểu: declarative registry mà không migrate swarm | LOW | DONE (E3) |
| 14 | `llm_client.py` dùng `requests` (generic HTTP + OpenRouter endpoint), KHÔNG phải vendor SDK — vi phạm chữ nghĩa provider-neutrality ở mức import-generic | `src/core/llm_client.py` (46 file references) | **KEEP + GATE** — grep-gate chấp nhận đúng 1 exception, docs transitional; MOVE defer | Rule là architectural: adapter đã cô lập provider; MOVE 46 referencing files = rủi ro > lợi v0.1 | MED | GATED (E1 boundary test) |
| 15 | Self-description stale: CLAUDE.md cite tree/forest/land (phantom) + "43 commands"; README chưa nói autonomous runtime | `CLAUDE.md`; `README.md`; `src/commands/COMMAND_REGISTRY.md` | **UPDATE** README + CLAUDE.md (lane E7); COMMAND_REGISTRY rewrite defer | §19: positioning + docs trung thực | LOW | DONE (E7) |
| 16 | Thiếu bộ docs kiến trúc v0.1 | NEW: `docs/architecture.md`, `docs/core-contract.md`, `docs/runtime-adapters.md`, `docs/capability-bus.md`, `docs/economic-bus.md`, `docs/buzz-runtime-adapter.md`, `docs/autonomy-model.md`; `CONTRIBUTING.md` đã có | **NEW/UPDATE** | §19 bắt buộc; docs-manager thực hiện | LOW | DONE (E7) |
| 17 | Scheduler unsandboxed | `src/daemon/scheduler.py` | **KEEP** — đã fix Wave 1 (fail-closed sanitizer) | Verified; không regression | — | VERIFIED |
| 18 | run.py wiring inert | `src/commands/run.py` | **KEEP + mở rộng** (inject capability_bus) | Wave 1 đã sửa gốc; E2 nối thêm bus | LOW | DONE (E2) |
| 19 | 3 Typer apps chưa đăng ký | `src/cli/app_setup.py:127-129` | **KEEP** — đã fix Wave 3 | Verified | — | VERIFIED |
| 20 | Tier-config duality; 4 route families payment | `engine/billing/tier_config.py`; `src/seed/config/tiers.py`; `src/gateway.py` mounts | **DEFER** | Live revenue paths; cần feature flags + replay tests riêng | MED | DEFERRED |
| 21 | `LLMRouter` thiếu `tool_call()` | `src/core/protocols.py:140-149`; `src/core/llm_router_adapter.py` | **REFACTOR** — thêm `tool_call()` vào Protocol + adapter (implement qua structured_output thật, docs limitation); tests ≥2 fake providers chứng minh cùng interface | §5: interface đủ 5 phương thức; không fake network | LOW-MED | NOT DONE in v0.1 — no lane assigned; carried to next actions |
| 22 | `stream()` yield 1 chunk (LLMClient không native streaming) | `src/core/llm_router_adapter.py:107ff` | **KEEP** + docs limitation | Wrap-không-rewrite; streaming thật là Phase sau | LOW | KEPT |

Phân loại tổng: KEEP=8 · REFACTOR=7 · WRAP/WIRE=1 · NEW=4 · DELETE=1 · DEFER=6.

## Deferred scope (v0.1 transparency)

The following are explicitly OUT of v0.1 (stop-condition discipline):

1. Real multi-step `plan()` + multi-agent `delegate()` (effort L).
2. GoalEngine conformance to `protocols.GoalEngine`.
3. MemoryStore convergence (3-way split stays).
4. Harness verifier merge + DAG scheduler swap.
5. MCP client-side (consuming external MCP servers).
6. Real x402/MPP settlement, marketplace, tokenomics, custody, financial execution.
7. New CLI surface (`mk mission/agent/run/inspect/verify/approve/mcp/runtime/app/pay`).
8. Full Sandbox/App Factory — only the `ExecutionRuntime` primitive ships.
9. Tier-config duality collapse, 4 payment route families merge,
   COMMAND_REGISTRY.md rewrite, funnel restoration (Zalo/tax/vn-setup).
10. MOVE `src/core/llm_client.py` out of `core/` (46 file references).

See [ARCHITECTURE_AFTER_PHASE_2.md](./ARCHITECTURE_AFTER_PHASE_2.md) for the full
gap/debt analysis and scored next actions.
