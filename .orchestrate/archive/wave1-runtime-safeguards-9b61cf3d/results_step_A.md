# STEP A RESULTS — fix run.py telemetry + wire governance/max_cost_usd/tracer

Base: main @ 7459010db (uncommitted working-tree changes, per instruction "KHÔNG commit")
Date: 2026-08-24
Status: COMPLETE

## Files Changed

| File | Change | LOC delta |
|------|--------|-----------|
| `src/commands/run.py` | Rewired `_build_runtime()` + `run_command()` | +49/-17 net (154 total) |
| `src/core/governance.py` | Hardening: explicit `return True` cuối `request_approval` | +4 |
| `src/core/runtime_adapter.py` | Gate-blocked results return ngay, không vào repair loop | +9/-1 |
| `tests/test_run_command_wiring.py` | Test mới | 181 dòng, 18 tests |

## Diff Summary

### src/commands/run.py
1. Xóa class `_NullTelemetry` (chỉ có `record_event`, gây AttributeError tại `emit()` đầu tiên). Thay bằng `telemetry=TelemetrySinkAdapter()` — conform `protocols.ObservabilitySink`.
2. Wire `governance=Governance()` — DEFAULT ON. Escape hatch duy nhất = env `GOVERNANCE_AUTO_APPROVE=true|1|yes` đã tồn tại (`governance.py:124`). KHÔNG thêm cờ CLI bypass.
3. Cost ceiling: `_resolve_max_cost_usd(cli_value)` — precedence CLI `--max-cost-usd` > env `MEKONG_MAX_COST_USD` > default `5.0`. Env invalid → cảnh báo vàng + fallback 5.0 (không crash build).
4. Tracer KHÔNG truyền qua constructor (kwarg không tồn tại): `tracer = MissionTracer(); runtime.start_mission(goal, tracer=tracer)` TRƯỚC `runtime.run(goal)`.
5. Docstring cập nhật: gates ON mặc định, review-class goals bị chặn khi chưa set GOVERNANCE_AUTO_APPROVE.

### src/core/governance.py (hardening mục 5 của plan)
`request_approval` thêm explicit `return True` cho non-review decisions — không còn fall-through trả `None`.

### src/core/runtime_adapter.py (xem Deviations #1)
- 3 nhánh gate-block trong `execute()` (FORBIDDEN, REVIEW-rejected, cost-ceiling) đánh dấu `meta["gate_blocked"] = True`.
- `_run_task_loop`: `if verification.passed or result.metadata.get("gate_blocked", False): return result` — gate verdict là quyết định chính sách deterministic, không retry được; trước đây loop repair chạy tới "Max repair retries (3) exceeded" và CHE mất error string thật của gate.

### tests/test_run_command_wiring.py (18 tests)
Fixture autouse isolate: chdir tmp_path (audit YAML không đụng repo), TelemetryCollector singleton trỏ output_dir tmp, delenv 2 env vars. Tất cả test đi qua runtime THẬT (không mock runtime/governance/cost).

## Verify Commands + Output

```
$ grep -c "_NullTelemetry" src/commands/run.py
0

$ python3 -c "from src.commands.run import _build_runtime; rt=_build_runtime(); print(type(rt._telemetry).__name__, type(rt._governance).__name__, rt._max_cost_usd)"
TelemetrySinkAdapter Governance 5.0

$ python3 -m pytest tests/test_run_command_wiring.py tests/test_runtime_safety.py tests/test_correlation_id.py tests/test_governance.py -q
88 passed  (sau khi thêm coverage hardening: wiring file riêng = 18 passed)

$ python3 -m ruff check src/commands/run.py tests/test_run_command_wiring.py
All checks passed!

# Parity (full suite, 33m49s):
$ python3 -m pytest tests/ -q
=== 223 failed, 7548 passed, 75 skipped in 2029.97s ===
Baseline frozen: 223 failed → count PARITY (223 == 223)

# Setiff trên mọi test file import module bị sửa (12 files, 162 tests):
1 failed, 161 passed — fail duy nhất là
tests/test_autonomous_loop.py::TestAutonomousLoop::test_full_loop_returns_result
đã nằm sẵn trong baseline (fail vì MagicMock không JSON-serializable trong memory path,
KHÔNG liên quan telemetry). ZERO new fails.
```

CLI smoke (CliRunner qua entry thật):
- `--goal "hello"` → exit 1 với Result.error từ dispatcher stub (loop chạy trọn observe/commit, KHÔNG còn AttributeError emit)
- `--goal "deploy production build"` → exit 1, panel hiện đúng verdict: `Error: Action requires human approval: Matched review pattern…`

## Acceptance Criteria (plan.md Bước A)

| # | Criterion | Status |
|---|-----------|--------|
| 1 | `grep -c "_NullTelemetry" run.py` → 0 | PASS |
| 2 | One-liner in `TelemetrySinkAdapter Governance 5.0` | PASS |
| 3 | `rt._telemetry` isinstance `ObservabilitySink` (runtime_checkable) | PASS |
| 4 | E2E không crash: `_build_runtime()` → run("hello") trả Result có task_id, qua observe/emit thật | PASS |
| 5 | Review-class "deploy production build" env unset → error chứa "Action requires human approval" | PASS |
| 6 | Forbidden "rm -rf /tmp/x" → error chứa "Action forbidden" | PASS |
| 7 | `GOVERNANCE_AUTO_APPROVE=true` → review goal đi qua gate | PASS |
| 8 | Sau run: `tracer.get_mission(rt._mission_id)` status success/failed + ≥1 step | PASS |
| 9 | `max_cost_usd=0.0000001` → execute/run trả "Cost ceiling exceeded" | PASS |
| 10 | pytest targets xanh (4 files) | PASS (88 passed) |
| 11 | ruff sạch trên files sửa | PASS |
| 12 | Parity ≤223 failed, zero new | PASS (223=223, set-diff sạch) |

## Protected Flows

Không đụng. `git status`: chỉ 3 file sửa + 1 test mới. Không file nào thuộc NOWPayments IPN chain hay license gate chain.

## Deviations

1. **Sửa `src/core/runtime_adapter.py` (+9/-1)** — constraint nói chỉ sửa khi plan chỉ định, ưu tiên wiring-side. LÝ DO BẮT BUỘC: verify thực nghiệm (trước fix) cho thấy repair loop retry gate-blocked results và error cuối luôn là "Max repair retries (3) exceeded", che mất "Action requires human approval" / "Action forbidden" / "Cost ceiling exceeded" → acceptance criteria #5/#6/#9 của chính plan IMPOSSIBLE ở mức run(). Gate ON mà verdict bị che = gate không thực sự engage (mâu thuẫn verbatim intent của task). Fix tối thiểu: metadata marker `gate_blocked` + early-return trong `_run_task_loop`; transient errors (vd dispatcher raise) vẫn giữ nguyên hành vi retry cũ.
2. **Bỏ `asyncio.run(runtime.run(goal))`** trong `run_command` → gọi trực tiếp `runtime.run(goal)`. `MekongCoreRuntimeImpl.run` là sync (`protocols.py:126`) — `asyncio.run(Result)` raise TypeError ngay ("An asyncio.Future, a coroutine or an awaitable is required"). Đây là crash thứ hai của prod path, nằm ngoài observe/emit. Wiring-side fix trong file được phép sửa.
3. **Sửa signature `_NullDispatcher.dispatch(task, agent=None)`** — runtime gọi `dispatch(task, task.agent)`; signature cũ `(task)` làm TypeError thay vì NotImplementedError mong muốn.
4. **Test gọi `rt.run(...)` trực tiếp** thay vì `asyncio.run(rt.run(...))` như acceptance criteria viết — vì run() sync (điểm 2). Ý nghĩa test không đổi.
5. **test_autonomous_loop::test_full_loop_returns_result vẫn đỏ** — plan đoán có thể xanh lại sau Defect 1 fix, nhưng nó tự build runtime bằng MagicMock telemetry nên không bao giờ chạm bug _NullTelemetry; nguyên nhân đỏ thật là MagicMock không JSON-serializable trong memory path (pre-existing, đã trong baseline 223).
6. **Thêm 2 test nhỏ ngoài danh sách tối thiểu**: invalid `MEKONG_MAX_COST_USD` fallback + hardening `request_approval` explicit True/False (che phần governance.py vừa sửa).

## Unresolved Questions

- Dispatcher production thật vẫn chưa wire (`_NullDispatcher` giữ nguyên theo scope Bước A — out-of-scope "plan()/delegate() upgrades").
- `--max-cost-usd` nhận giá trị âm/nonsense (float parse OK nhưng < 0) sẽ lập tức kích hoạt cost guard ở execute đầu tiên — hành vi fail-closed hợp lý, chưa thêm validate riêng (YAGNI; có thể siết nếu orchestrator muốn).
