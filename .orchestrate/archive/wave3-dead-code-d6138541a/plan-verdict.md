CONDITIONAL PASS ROUND: 1

# Plan Verdict — Wave 3 Dead-Code Deletion (Items 10–18) + Push Pending Commit

**Plan:** `/Users/macbook/mekong-cli/.orchestrate/latest/plan.md`
**Task:** `/Users/macbook/mekong-cli/.orchestrate/latest/task.md`
**Evaluator:** Sun Tzu (plan gate, pre-execution)
**Ngày:** 2026-08-25

---

## Verdict

**CONDITIONAL PASS** — Plan đạt chất lượng cao: goal rõ, decomposition đủ 9 items, mọi claim dead-code đã được evaluator verify độc lập tại HEAD `f0f210de1`, risks có mitigation + escrow, gates đo lường được. KHÔNG có HIGH/blocking issue. Còn 1 MED finding (P3.1 chưa kê khai số phận `cli/ui/banner.py` + `cli/ui/help.py` — 2 file import `cli.theme` sẽ gãy sau khi move) + vài LOW findings → chuyển thành escrow TODO, không chặn pipeline.

---

## Evidence (evaluator tự kiểm chứng, không dựa vào summary của planner)

### Git state
- `git status -sb`: `## main...origin/main [ahead 1]`, HEAD = `f0f210de1` ✓ khớp plan.
- `git diff-tree --name-only -r f0f210de1 | grep -cv "^\.orchestrate/"` → **0** — commit 100% `.orchestrate/**`, docs-only claim đúng, an toàn push thẳng main.
- Baseline fail-set tồn tại: `.orchestrate/archive/audit-refresh-7459010db/failed_tests_head_0878f966f.txt` = **223 dòng** đúng như plan ghi.

### CI gate set baseline
- `gh run list --branch main --limit 12` tại `0365918f5` (PR #5): đúng 11 workflows — 10 đỏ (CI, Test Suite, Quality Gates, AI-Native CI/CD — 5 Gates, Command Fabric Release Gate, Factory Integrity, Nhịp Điệu Xanh, smoke-tests.yml, release.yml, deploy-cf.yml) + **Security Hardening & Attestation xanh** ✓ khớp plan §1/§3.5. Acceptance "gate set không đổi" là đo được.

### Verify từng item tại HEAD (grep + ls độc lập)

| Item | Evaluator verify | Kết quả |
|------|------------------|---------|
| 10 | 2 file `.legacy` tồn tại (17K/24.5K); grep `polar_webhook` trong src/tests chỉ ra: comment LEGACY (`gateway.py:100`, `webhooks/router.py:15`), log-file name + bảng `polar_webhook_events` trong `billing_routes.py` (code sống, KHÔNG phải target), handlers trùng tên ở `polymarket/billing.py`, `raas/billing.py` (không liên quan file bị xóa). `pytest.ini: python_files = test_*.py` → `.legacy` không bị collect ✓ | Claim đúng |
| 11 | `src/old/a2ui/` có 4 file; grep `src\.old\|from old\|import old` = **0 matches** | Claim đúng (1 chi tiết sai — xem Finding 3) |
| 12 | `founder_vc/__init__.py` 223B, `founder_ipo/__init__.py` 212B; grep `founder_vc\|founder_ipo` = **0 references** | Claim đúng |
| 13 | `executor.py:21 from .llm_config import ModelConfig` + `:87 def run_llm` — audit claim "zero importers" ĐÚNG LÀ STALE như plan phát hiện; grep `run_llm` ngoài executor.py = **0 callers**; grep `daemon.llm_router` = **0 importers** | Plan phát hiện stale-claim CHÍNH XÁC; phương án split (xóa llm_router + cặp run_llm/llm_config) có bằng chứng |
| 14 | `sops-engine/__init__.py` 125B, `raas_auth/__init__.py` 419B; grep `sops-engine`, `observability.raas_auth` = **0 refs**; đọc `src/harness/observability/__init__.py` — chỉ import telemetry_collector/`.tracing`/metrics/health_reporter, KHÔNG đụng raas_auth ✓ | Claim đúng |
| 15 | grep `core.tracing` → importer duy nhất: `tests/test_tracing.py`. Lưu ý quan trọng đã verify: `src/harness/observability/tracing.py` là file KHÁC (được `observability/__init__.py` import, ở lại) — plan không nhầm lẫn 2 file này ✓ | Claim đúng |
| 16 | grep `setup_telemetry(` = **0 call sites** (chỉ docstring + re-export `telemetry/__init__.py:18,58`); `observe_agent` nằm ở `telemetry/instrument.py` (line 19 import), KHÔNG nằm trong sdk_setup.py → xóa sdk_setup.py không chạm observe_agent ✓ | Claim đúng; caution per-symbol của plan là đúng chỗ |
| 17 | `workflows/scripts/zenos-full-redesign-wf_6f2b5978-3f8.js` tồn tại; grep trong `.github/`, `workflows/`, `pyproject.toml` = **0 refs** (chỉ self-reference trong file) | Claim đúng |
| 18 | `cli/tui/streaming.py` importer duy nhất: `tests/test_tui_streaming.py:23` ✓; `src/cli/tui/` hiện chỉ có `router.py` (namespace package, không `__init__.py` — test_nl_routing vẫn import `src.cli.tui.router` bình thường → move vào không cần `__init__`) ✓ | Claim đúng (thiếu 1 chi tiết — Finding 1) |

### Dry-run P3.2 (evaluator tự chạy)
- `build_app()` → **33 groups**; thêm `billing_commands.app` + `pev_commands.pev_app` + `usage_commands.app` → **36 groups, 0 duplicate names, cả 3 có mặt** — reproduce chính xác claim của plan.
- Grep tests: không test nào assert cứng `== 33` trên build_app output; `test_plugin_integration.py:82` assert `len==0` trên `typer.Typer()` root mới tạo (fresh root, không phải build_app) → không rủi ro gãy assertion ✓.

### Protected flows
- Deletion set (items 10–18) giao với protected set (`src/raas/nowpayments_*`, `src/middleware/license_gate.py`, `src/lib/raas_gate/`, `src/gateway.py`) = **0** — cross-check bằng grep, không file nào trong deletion set nằm trong protected chain ✓.

---

## Findings

1. **[MED] P3.1 bỏ sót 2 importer của `cli.theme` ngoài streaming.py.** Grep của evaluator: `from cli.theme import` xuất hiện tại 3 file — `cli/tui/streaming.py:40` (plan đã kê khai), `cli/ui/banner.py:10`, `cli/ui/help.py:11` (plan KHÔNG kê khai). Sau khi move `cli/theme.py` → `src/cli/tui/theme.py`, banner.py và help.py sẽ mang import gãy. Verify thêm: banner/help có **0 importers** (grep `cli.ui|banner` ngoài chính `cli/ui/` = 0 matches, kể cả `cli/__init__.py` không import chúng) → chúng là dead code, không test nào collect, ruff chỉ chạy `src/ tests/` nên không gate nào bắt được. Hệ quả: không gãy test/runtime, nhưng wave "xóa dead code" lại để lại 2 file dead với import gãy — đi ngược mục tiêu. Plan Risk 4 có mitigation "grep bắt được trước khi move" nên executor sẽ thấy, nhưng plan chưa kê khai ACTION cho 2 file này. → Chuyển thành escrow TODO (Condition below), không chặn vì mitigation + escrow P3.1 (bỏ fold) đã có sẵn.

2. **[LOW] Số liệu test count trong plan lệch với thực tế.** Plan ghi test_tracing.py = 21 tests, test_tui_streaming.py = 39 tests; grep `def test_` thực tế: **23** và **43**. Gate parity của plan đọc theo normalized fail-set diff (đúng) nên không ảnh hưởng pass/fail, nhưng Assumption 3 ("passed ≈ 7576 − 21 − 39...") và expected-delta trong ship report sẽ sai số nếu không cập nhật. Executor phải dùng số thực tế khi ghi expected delta.

3. **[LOW] Chi tiết drift claim item 11 sai.** Plan bảng §1: "old thiếu `component_helpers.py`" — thực tế `find src/old` cho thấy `src/old/a2ui/component_helpers.py` CÓ tồn tại (4 file: `__init__`, `components`, `renderer`, `component_helpers`). Kết luận DELETE vẫn đúng vì bằng chứng quyết định là 0 importers (đã verify), nhưng chi tiết bằng chứng ghi sai cần sửa khi cập nhật docs (P4.1) để assessment không lưu thông tin sai.

4. **[LOW] Working tree đang có uncommitted changes** (`M .orchestrate/latest/plan.md`, `M .orchestrate/latest/task.md`) — là pipeline artifacts, plan đã nói archive+commit sau merge. Nhắc executor KHÔNG để chúng lẫn vào 5 commit bucket (chỉ stage đúng file deletion/code).

---

## Conditions (escrow TODO — KHÔNG chặn pipeline, phải ghi vào ship-report)

1. **P3.1 phải xử lý banner/help trước/khi move theme** — executor khi grep pre-move (Risk 4) sẽ thấy `cli/ui/banner.py` + `cli/ui/help.py`; chọn 1 trong 3 và ghi vào ship-report: (a) xóa luôn banner.py + help.py (dead, 0 importers — phù hợp tinh thần wave 3, khuyến nghị), (b) sửa import của chúng sang path mới, hoặc (c) escrow toàn bộ P3.1 theo bảng §6 nếu không muốn mở rộng diff. KHÔNG được leave import gãy trong tree.
2. **Cập nhật expected test deltas bằng số thực tế**: test_tracing.py xóa = −23 passed (không phải −21); test_tui_streaming.py = 43 tests di chuyển, vẫn pass (không giảm). Ghi vào ship-report trước khi chạy parity.
3. **P4.1**: khi mark item 11 DONE trong ARCHITECTURE_ASSESSMENT.md, sửa chi tiết "old thiếu component_helpers.py" cho đúng thực tế (old có đủ 4 file; bằng chứng dead là 0 importers).
4. **Commit hygiene**: 5 commit bucket chỉ chứa file thuộc scope từng bucket; `.orchestrate/latest/*` changes chỉ vào commit archive sau merge.

---

## Out-of-scope observations (không chặn, tham khảo cho wave sau)

- `src/harness/observability/tracing.py` và `src/core/tracing.py` cùng kích thước 8777 bytes — nhiều khả năng là bản copy. Item 15 xóa `src/core/tracing.py` sẽ để lại harness copy làm bản duy nhất. Wave 4 (convergence/dedup) nên xem xét cặp file này.
- Root `cli/` còn lại (commands/ 11 files, handlers/, docs.py, strategy.py, developer.py, ui/) — verify của evaluator xác nhận 0 importers từ src/tests/.github (kể cả `tests/benchmark_cli.py` chỉ chạy subprocess, không import) → escrow P3.3 của plan là đúng chỗ; bằng chứng 0-importer này có thể dùng luôn cho wave sau.

---

## Scope check

- Plan phủ đúng scope task.md: push `f0f210de1` + items 10–18 theo ARCHITECTURE_ASSESSMENT.md, KHÔNG lan sang Wave 4, KHÔNG đụng protected flows (verified 0 giao nhau).
- Không có bước irreversible thiếu gate: mọi deletion nằm trong commit bucket có parity gate + rollback = `git revert` single squash commit (RPO=0, đúng cho CLI/library repo không deploy).
- Push thẳng main của P0.1 được task.md ủy quyền rõ (docs-only) và evaluator đã verify commit chỉ chứa `.orchestrate/**`.

**Kết luận:** Pipeline tiếp tục với 4 escrow TODO trên. Verdict: **CONDITIONAL PASS**.
