# PLAN — Wave 1: Fix Critical Defects from Architecture Audit

Base: main @ 7459010db · Branch: `feat/wave1-defect-fixes` · Date: 2026-08-24
Task: `.orchestrate/latest/task.md` · Audit: `docs/architecture/ARCHITECTURE_ASSESSMENT.md`
Baseline parity: 223 failed frozen tại `.orchestrate/archive/audit-refresh-7459010db/failed_tests_head_0878f966f.txt`

---

## 1. Reframed problem

Ba defect đã được audit verify tĩnh, giờ phải sửa THẬT (không report-only):

1. **`mekong run` chết ngay ở observe() đầu tiên** — prod wiring truyền `_NullTelemetry` (chỉ có `record_event`) trong khi runtime gọi `.emit()` vô điều kiện; đồng thời 3 gate autonomy (governance approval, cost ceiling, mission tracing) đang INERT vì không được inject.
2. **MCP→Capability bridge chết im lặng** — adapter import class không tồn tại (`MCPServer` thay vì `MekongMcpServer`), try/except nuốt lỗi → sync_from_mcp trả 0 tools; handler lookup bỏ sót prefix `cc_`. Test hiện tại che cả hai bug bằng MagicMock server.
3. **Daemon scheduler thực thi nội dung file như raw shell** — không sanitizer, không allowlist, không approval; lỗ hổng arbitrary-execution duy nhất của repo.

Điểm quyết định kỹ thuật (đã chốt, có bằng chứng):
- **emit() vs record_event()**: conform vào `protocols.ObservabilitySink` (:182-186, định nghĩa `emit`+`flush`). Runtime là canonical loop (buzz path + tests cùng dùng); đổi runtime sang `record_event()` sẽ phá protocol và ripple rộng. Fix = dùng `TelemetrySinkAdapter` (`src/core/telemetry_sink_adapter.py`) — đã tồn tại, wrap `TelemetryCollector`, map đúng các event_type mà runtime emit (`task_completed`, `run_completed`). **Xóa `_NullTelemetry`.**
- **Governance default ON** — task verbatim yêu cầu "gates actually engage". SAFE đi qua tự do; REVIEW_REQUIRED bị chặn trừ khi env `GOVERNANCE_AUTO_APPROVE=true|1|yes` (bypass đã tồn tại, `governance.py:124`); FORBIDDEN luôn chặn. Không thêm CLI flag mới (KISS) — escape hatch là env var có sẵn, ghi rõ trong docstring/help.
- **Tracer KHÔNG truyền qua constructor** — `MekongCoreRuntimeImpl.__init__` (runtime_adapter.py:120) KHÔNG nhận kwarg tracer (audit doc dòng 70 sai ở điểm này). Tracer gắn qua `runtime.start_mission(goal, tracer=MissionTracer())`; plain `run()` không tự gọi start_mission nên nếu không gọi thì `_mission_id=None` và `_trace_step/_finish_mission` no-op.
- **Scheduler vi phạm → DLQ, không skip+log** — fail-closed theo pattern `tool_registry.py:274-290`; skip+log để file nằm lại watch dir → quét lại mỗi poll (vòng lặp retry ồn ào), còn mark_processed thì archive "processed" mang nghĩa "đã chạy". DLQ + reason file dùng infra `DeadLetterQueue.move_to_dlq(path reason)` có sẵn.

---

## 2. Work checklist

### Bước A — fix run.py telemetry + wire governance/max_cost_usd/tracer

Files:
- Sửa `src/commands/run.py`
- Tạo test mới `tests/test_run_command_wiring.py`

Thay đổi chính xác trong `_build_runtime()` + `run_command()`:
1. Xóa class `_NullTelemetry` (run.py:54-58). Thay `telemetry=_NullTelemetry()` bằng `telemetry=TelemetrySinkAdapter()` (import từ `src.core.telemetry_sink_adapter`).
2. Inject `governance=Governance()` (import từ `src.core.governance`).
3. Cost ceiling: `max_cost_usd=float(os.getenv("MEKONG_MAX_COST_USD", "5.0"))`, cộng option CLI `--max-cost-usd` (override env). Guard hiệu lực thật vì `LLMRouterAdapter.estimate_cost` trả dict có `cost_usd` (llm_router_adapter.py:86-93) — đúng shape mà `_check_cost_guard` đọc (runtime_adapter.py:420).
4. Trong `run_command()`: tạo `tracer = MissionTracer()` rồi **gọi `runtime.start_mission(goal, tracer=tracer)` TRƯỚC `runtime.run(goal)`** (không truyền tracer vào constructor — sẽ TypeError).
5. Hardening 1 dòng (optional, khuyến nghị): `Governance.request_approval` hiện fall-through trả `None` cho action không requires_approval (governance.py:111-137). Thêm explicit `return True` cuối hàm — dead path hôm nay (chỉ gọi khi REVIEW_REQUIRED), nhưng phòng ngừa.
6. Cập nhật docstring run.py ghi rõ: review-class goals bị chặn khi chưa set `GOVERNANCE_AUTO_APPROVE`.

Acceptance criteria (file-level):
- [ ] `grep -c "_NullTelemetry" src/commands/run.py` → 0
- [ ] `python3 -c "from src.commands.run import _build_runtime; rt=_build_runtime(); print(type(rt._telemetry).__name__, type(rt._governance).__name__, rt._max_cost_usd)"` → in `TelemetrySinkAdapter Governance 5.0`
- [ ] `tests/test_run_command_wiring.py` gồm ít nhất:
  - `rt._telemetry` thỏa `isinstance(rt._telemetry, ObservabilitySink)` (protocol runtime_checkable)
  - End-to-end KHÔNG crash: `_build_runtime()` → `asyncio.run(rt.run("hello"))` trả Result có task_id (dispatcher raise được execute() bắt thành error → observe/emit chạy qua — đây chính là crash path cũ)
  - Goal review-class (`"deploy production build"`) → Result.error chứa "requires human approval" khi env unset (monkeypatch.delenv)
  - Goal forbidden (`"rm -rf /tmp/x"`) → error "forbidden"
  - `GOVERNANCE_AUTO_APPROVE=true` → goal review-class đi qua gate
  - Sau run: `tracer.get_mission(rt._mission_id)` có status success/failed và ≥1 step
  - Cost guard: runtime với `max_cost_usd=0.0000001` → execute trả error "Cost ceiling exceeded"
- Verify: `python3 -m pytest tests/test_run_command_wiring.py tests/test_runtime_safety.py tests/test_correlation_id.py tests/test_governance.py -v` xanh; `python3 -m ruff check src/commands/run.py tests/test_run_command_wiring.py` sạch.

### Bước B — fix MCP capability adapter

Files:
- Sửa `src/core/adapters/mcp_capability_adapter.py`
- Viết lại phần mock trong `tests/test_mcp_capability_adapter.py`

Thay đổi chính xác:
1. Dòng 55: `from src.core.mcp_server import MCPServer` → `from src.core.mcp_server import MekongMcpServer`; `self._mcp_server = MekongMcpServer()`.
2. Handler lookup (dòng ~85): strip prefix trước khi build tên method — `base = tool_name[3:] if tool_name.startswith("cc_") else tool_name`; `handler_name = f"_handle_{base}"`. **Giữ nguyên capability id `mcp:cc_<name>`** (id = tên tool public như server expose; không consumer nào khác phụ thuộc id dạng khác — grep toàn repo chỉ thấy docstring).
3. Cập nhật docstring module (ví dụ `mcp:tasks_list` → `mcp:cc_tasks_list`) và metadata `"handler"` trong Capability ghi đúng tên method sau strip.

Acceptance criteria:
- [ ] `python3 -c "from src.core.adapters.mcp_capability_adapter import MCPCapabilityAdapter as A; a=A(); s=a._get_mcp_server(); print(type(s).__name__)"` → `MekongMcpServer` (env có SDK mcp — đã verify import OK)
- [ ] Test BỎ MagicMock-server, dùng REAL server: `sync_from_mcp()` với default `_get_mcp_server()` path đăng ký đủ tools (assert `len(caps) >= 20`, đối chiếu `len(server.create_app()._tools)` — hiện 25 tool cc_*)
- [ ] Test thực thi handler thật không mock-che: `bus.get("mcp:cc_skills_list").execute({})` → `{"ok": True}` (read-only, an toàn); `bus.get("mcp:cc_mcp_list").execute({})` → ok=True. Tối thiểu 2 tool cc_* chạy thật qua handler đã strip prefix
- [ ] Giữ `_FakeBus` (test seam hợp lệ cho bus; conformance bus đã test riêng) — chỉ loại bỏ mask trên server
- [ ] Test fallback unknown-tool vẫn hoạt động; test idempotent sync vẫn pass
- Verify: `python3 -m pytest tests/test_mcp_capability_adapter.py tests/test_mcp_server.py tests/test_mcp_server_integration.py -v` xanh; ruff sạch trên file sửa.

### Bước C — sandbox daemon scheduler

Files:
- Sửa `src/daemon/scheduler.py` (và có thể thêm module nhỏ `src/daemon/sandbox.py` nếu vượt 200 LOC — tuân thủ rule file-size)
- Mở rộng `tests/test_daemon_scheduler.py`

Thiết kế (layered, tái dùng primitive có sẵn):
1. `DaemonScheduler.__init__`: dựng `CommandSanitizer(strict_mode=True)` (pattern copy từ `tool_registry.py:274-289` — fail-closed: import lỗi sanitizer → block, không bao giờ execute).
2. Allowlist first-token: `cfg.get("allowed_commands")` merge với built-in conservative default (vd `["echo","ls","cat","pwd","date"]`). Token đầu của content phải thuộc allowlist; strict mode chặn sẵn suspicious (`python -c`, `node -e`, `nc`, `base64 -d`, `eval`, `exec`) và dangerous (`sudo`, `curl|sh`, chaining `; && || |` + newline — mọi file đa dòng sẽ bị chặn bởi `_CHAINING_RE`).
3. Flow `_process_mission`: đọc content → sanitize → **nếu không safe hoặc token đầu không thuộc allowlist → `dlq.move_to_dlq(mission_path, reason=sanitizer.blocked_reason)` + `journal.record_mission(success=False, error=reason)` + return. KHÔNG gọi executor.run_shell.** Không retry loop cho violation (violation là untrusted input, không phải failure thoáng qua).
4. Không thêm env bypass trong daemon (khác GOVERNANCE_AUTO_APPROVE của CLI tương tác) — daemon headless, operator cấu hình allowlist qua config là đường phê duyệt.
5. PostGate verify_commands (operator-provided) giữ nguyên — out of scope.

Acceptance criteria:
- [ ] Content nguy hiểm `"rm -rf / && echo pwned"` → run_shell KHÔNG được gọi (spy record), file chuyển vào dlq dir, có `.reason` file
- [ ] Content đa dòng → DLQ (chaining/newline)
- [ ] Content allowlisted `"echo hello"` (cfg `allowed_commands=["echo"]`) → run_shell gọi bình thường → archive như cũ
- [ ] Content safe nhưng ngoài allowlist (vd `python3 script.py`, default cfg) → DLQ với reason nói rõ allowlist
- [ ] Strict mode: `"echo ok; python3 -c 'import os'"` variant đơn lẻ `python3 -c ...` → DLQ dù python3 có trong allowlist (suspicious pattern strict)
- [ ] Behavior cũ giữ nguyên cho luồng hợp lệ: success→archive, fail→retry→DLQ sau max_retries (các test hiện tại trong TestDaemonScheduler phải vẫn xanh)
- Verify: `python3 -m pytest tests/test_daemon_scheduler.py tests/test_command_sanitizer_security.py -v` xanh; ruff sạch.

---

## 3. Risks & gates

Protected flows — KHÔNG đụng (không file nào dưới đây nằm trong danh sách sửa):
- NOWPayments IPN webhook → tier activation: `src/api/webhooks/router.py`, `src/raas/nowpayments_router.py`
- License gate chain: `engine/license/` ↔ `src/lib/raas_gate/__init__.py` ↔ `src/middleware/license_gate.py` ↔ `src/gateway.py`
- Nếu diff chạm bất kỳ file nào ở trên → dừng, escalate về orchestrator.

Gates mỗi bước (bắt buộc trước khi commit):
1. `python3 -m pytest <target files của bước> -v` — xanh hết
2. `python3 -m ruff check src/ tests/` — sạch
3. Parity check: `python3 -m pytest tests/ -q 2>&1 | tail -5` — số failed ≤ 223 và **không có test NEW fail** so với baseline file (diff set). Lưu ý: fixing Defect 1 có thể làm MỘT SỐ test baseline-red quay lại xanh (vd `test_autonomous_loop.py::test_full_loop_returns_result` có thể đang đỏ vì chính bug này) → giảm số failed là ĐIỂM CỘNG, ghi vào PR.
4. Real implementation only: cấm mock để CHE defect (MagicMock che import/handler lookup bị cấm; spy/boundary-mock cho network-LLM trong test là hợp lệ).

Risks cụ thể:
- Governance ON làm goal kiểu "Deploy production build" (chính ví dụ trong docstring run.py!) giờ cần approval → đây là behavior MONG MUỐN theo task verbatim; ghi rõ breaking-change note trong PR body.
- `create_app()` phụ thuộc internal FastMCP `app._tool_manager.list_tools()` (mcp_server.py:201-204) — nếu SDK version đổi làm gãy, test B sẽ bắt được; không sửa ngoài scope.
- Sanitizer chặn mọi multi-line content → daemon chỉ nhận single-command files. Ghi rõ vào docstring scheduler + PR note (thay đổi semantics có chủ đích).

## 4. Agent đề xuất từng bước

| Bước | Implement | Verify | Ghi chú |
|------|-----------|--------|---------|
| A | `fullstack-developer` (prompt kèm plan mục Bước A + đường dẫn file + acceptance criteria) | `tester` chạy pytest targets + parity diff + ruff | xong mới sang B |
| B | `fullstack-developer` | `tester` (đặc biệt assert real-server discovery ≥20 caps) | độc lập A về code nhưng chạy tuần tự để parity gate sạch |
| C | `fullstack-developer` | `tester` + `code-reviewer` (security-sensitive — review sanitizer flow) | M-effort, nhiều nhất |
| Ship | `git-manager` (conventional commits) | `suntzu` verdict trước khi merge (khuyến nghị) | |

Work context: `/Users/macbook/mekong-cli`. Reports: `/Users/macbook/mekong-cli/plans/reports/`. Plans: `/Users/macbook/mekong-cli/plans/`.

## 5. Ship plan

1. `git checkout -b feat/wave1-defect-fixes` từ main @ 7459010db. **Không stage thay đổi `.orchestrate/`** (deletions/untracked thuộc pipeline quản lý) — commits chỉ code + tests.
2. Conventional commits (1 commit/bước, message không nhắc mã plan/defect):
   - `fix(run): wire observability sink, governance, cost guard and mission tracer into production runtime`
   - `fix(adapters): import MekongMcpServer and resolve cc_-prefixed tool handlers`
   - `fix(daemon): sandbox mission execution behind strict sanitizer and command allowlist`
3. Push → mở PR vào main. Body ghi: 3 fixes, breaking-change note (review goals cần GOVERNANCE_AUTO_APPROVE), baseline-parity evidence (failed ≤ 223, zero new), smoke output.
4. CI kỳ vọng: docs gate XANH; job đỏ khác (pnpm-lock.yaml config debt) = pre-existing escrow, KHÔNG thuộc scope này — cite trong PR, không cố sửa.
5. Squash merge sau khi tester báo parity PASS (+ suntzu CONDITIONAL PASS trở lên nếu có chạy).
6. Smoke post-merge trên main:
   - `mekong --help` exit 0
   - `python3 -c "from src.commands.run import _build_runtime; rt=_build_runtime(); assert hasattr(rt._telemetry,'emit') and rt._governance is not None and rt._max_cost_usd"`
   - `python3 -c "from src.core.adapters.mcp_capability_adapter import MCPCapabilityAdapter; a=MCPCapabilityAdapter(); assert type(a._get_mcp_server()).__name__=='MekongMcpServer'"`
7. **KHÔNG deploy** (theo task). Out of scope giữ nguyên: defect 4 masked imports, dead-code waves, plan()/delegate().
