# Wave 3 Plan — Push Pending Commit + Dead-Code Deletion (Items 10–18)

**Ngày:** 2026-08-25
**Repo:** /Users/macbook/mekong-cli (main, ahead origin/main 1 commit: `f0f210de1`)
**Nguồn:** task.md — user chọn "1+2"
**Branch làm việc:** `feat/wave3-dead-code` từ HEAD `f0f210de1` (sau khi push)
**Baseline parity:** 223 failed / 7576 passed / 75 skipped (frozen fail-set: `.orchestrate/archive/audit-refresh-7459010db/failed_tests_head_0878f966f.txt`, 223 dòng)
**Assessment nguồn:** `docs/architecture/ARCHITECTURE_ASSESSMENT.md` mục "File-Level Implementation Order" → Wave 3, items 10–18

---

## 1. Reframed Problem

Vấn đề thực sự KHÔNG phải là "xóa code chết cho gọn". Vấn đề là: sau 3 đợt ship (audit refresh PR #3, Wave 1 runtime safeguards PR #4, Wave 2 masked imports PR #5), toàn bộ 4 critical defects đã được fix, và bước đúng kế tiếp theo assessment là **cắt bớt surface area đã được audit xác nhận là dead** — để các wave sau (Wave 4 convergence: planner/verifier dedup, MemoryStore) làm việc trên một cây mã nhỏ hơn, ít chỗ trốn bug hơn. Deletion là công việc có risk ĐO LƯỜNG ĐƯỢC (zero importers = zero behavioral change) nhưng chỉ an toàn nếu từng claim được verify lại tại HEAD hiện tại — vì audit refresh chạy ở HEAD `0878f966f`, còn repo đã đi qua 2 merge kể từ đó.

Đi kèm là một việc housekeeping độc lập: commit docs-only `f0f210de1` đang treo trên local main — push ngay để (a) không mang nó lẫn vào PR Wave 3, (b) có baseline sạch để branch từ.

**Kết quả verify sơ bộ tại HEAD `f0f210de1` (quan trọng — 1 claim của audit đã stale):**

| Item | Target | Claim audit | Verify tại HEAD | Kết luận |
|------|--------|-------------|-----------------|----------|
| 10 | `src/api/polar_webhook.py.legacy` + `tests/api/test_polar_webhook.py.legacy` | 0 importers, superseded bởi `src/api/webhooks/router.py` | Cả 2 file tồn tại; grep "polar_webhook" chỉ còn comment LEGACY (`src/gateway.py:100`, `src/api/webhooks/router.py:15`) và code KHÔNG liên quan (`billing_routes.py` dùng tên log-file); `.legacy` extension nên pytest bỏ qua | **DELETE ok** |
| 11 | `src/old/` (a2ui copy) | zero importers | 4 file tồn tại; test dùng `src.a2ui` (bản live), KHÔNG ai import `src.old`; diff với `src/a2ui` đã drift (old thiếu `component_helpers.py`) | **DELETE ok** |
| 12 | `src/core/founder_vc/__init__.py`, `src/core/founder_ipo/__init__.py` | docstring-only shells | Đúng: mỗi package chỉ 1 `__init__.py` 212–223 bytes, nội dung license header + docstring; grep toàn repo = 0 references | **DELETE ok** (xóa cả directory) |
| 13 | `src/daemon/llm_router.py`, `src/daemon/llm_config.py` | zero importers post-f7d420c75 | ⚠️ **CLAIM STALE**: `src/daemon/executor.py:21` vẫn `from .llm_config import ModelConfig`. Tuy nhiên `executor.run_llm()` (hàm duy nhất dùng ModelConfig) có **0 callers** trong src+tests; riêng `llm_router.py` thì đúng là 0 importers | **SPLIT**: xóa `llm_router.py` nguyên vẹn; với `llm_config.py`: xóa cùng `run_llm()` method trong executor (dead method + dead dependency cùng lúc) — hoặc escrow nếu muốn tối thiểu hóa diff |
| 14a | `src/harness/sops-engine/` | empty stub | Đúng: 1 file `__init__.py` 125 bytes license-only; 0 importers | **DELETE ok** |
| 14b | `src/harness/observability/raas_auth/` | always-False stub, real client `src/core/raas_auth/` (9+ importers) | Đúng: stub 419 bytes, `authenticate()` return False; grep xác nhận mọi consumer đều import `src.core.raas_auth` (19 sites); `observability/__init__.py` KHÔNG export nó | **DELETE ok** |
| 15 | `src/core/tracing.py` | test-only consumers, overlap telemetry_collector | Đúng: duy nhất `tests/test_tracing.py` import (21 tests, đang PASS); production code 0 imports. Xóa module ⇒ phải xóa luôn `tests/test_tracing.py` | **DELETE cả hai**, ghi rõ trong commit message |
| 16 | `setup_telemetry` export trong `src/core/telemetry/sdk_setup.py` | exported never called, gateway dùng `telemetry_init.py` | Đúng: `setup_telemetry` được re-export ở `src/core/telemetry/__init__.py:18,58` nhưng 0 call sites trong src/tests; `src/gateway.py:60` dùng `telemetry_init.init_telemetry`. **Lưu ý**: docstring sdk_setup nói "Call in cli/main.py or FastAPI lifespan" — không site nào làm vậy | **Xóa function + re-export + entry `__all__`**. Toàn bộ `sdk_setup.py` sẽ rỗng ý nghĩa — cân nhắc xóa luôn file + dọn `__init__.py`; nếu giữ file thì chỉ vì docstring. Quyết định: xóa cả file, giữ `observe_agent` nếu nó nằm ở module khác (verify khi execute: `grep observe_agent`) |
| 17 | zenos scripts dưới `workflows/scripts/` | zero references | Đúng: duy nhất 1 file JS `zenos-full-redesign-wf_6f2b5978-3f8.js` (artifact wf_6f2b5978, chỉ được nhắc trong journal cũ `docs/journals/2025-06-18`); không CI/workflow nào tham chiếu | **DELETE ok** (thư mục `workflows/scripts/` trống theo đó cũng xóa) |
| 18 | KEEP-flagged: fold root `cli/tui/streaming.py` vào `src/cli/tui/`; register-or-delete 3 Typer apps | streaming test-only; billing/pev/usage chưa register | streaming: duy nhất `tests/test_tui_streaming.py:23` import `cli.tui.streaming` (39 tests PASS); phụ thuộc `cli.theme`. 3 apps tồn tại, có tests riêng (`tests/test_pev_commands.py` 21 tests, `tests/cli/test_usage_commands.py`, billing) và dry-run register thành công 33→36 groups không collision. **KHÔNG test nào assert số group == 33** (đã grep) | **REGISTER 3 apps** (không delete — code có tests thật). **Fold streaming**: move `cli/theme.py` + `cli/tui/streaming.py` → `src/cli/tui/`, sửa import trong test. Root `cli/` còn lại (`commands/`, `docs.py`, `strategy.py`, `developer.py`, `ui/`) — chỉ được tham chiếu bởi `tests/benchmark_cli.py` (không được pytest collect, standalone script) ⇒ **escrow** phần quyết định xóa root `cli/` còn lại |

**CI context (verified qua `gh run list`):** Gate set tại cả 2 merge trước (`9b61cf3d7`, `0365918f5`) giống hệt nhau — 11 workflows: 10 đỏ (CI, Test Suite, Quality Gates, AI-Native CI/CD — 5 Gates, Command Fabric Release Gate, Factory Integrity, Nhịp Điệu Xanh, deploy-cf.yml, release.yml, smoke-tests.yml) + 1 xanh (Security Hardening & Attestation). Test Suite đỏ tại bước **Lint** (ruff 0.x cũ hơn local? KHÔNG — lỗi là ruff check chạy trên checkout với config khác; local `ruff check src/ tests/` = All checks passed với ruff 0.15.18). Đây là repo debt có sẵn, KHÔNG phải blocker mới. Acceptance cho merge: gate set sau merge phải **đúng bằng set này** — không gate mới đỏ thêm, Security Hardening vẫn xanh.

---

## 2. Work Checklist

### Phase 0 — Push pending commit (ĐỘC LẬP, LÀM TRƯỚC)

- [ ] **P0.1** `git push origin main` (commit `f0f210de1`, docs-only archive artifacts — an toàn push thẳng main)
  - Agent: **git-manager**
  - Acceptance: `git status` → "up to date with origin/main"; `gh run list --branch main --limit 11` xuất hiện runs mới cho `f0f210de1`
- [ ] **P0.2** Verify CI gate set tại `f0f210de1` = baseline set (10 đỏ + Security Hardening xanh)
  - Agent: **tester**
  - Acceptance: so sánh bằng `gh run list` — không có workflow MỚI nào xuất hiện hay đổi trạng thái so với set tại `0365918f5`
- [ ] **P0.3** Tạo branch: `git checkout -b feat/wave3-dead-code` từ `f0f210de1`

### Phase 1 — Deletions zero-importer (items 10–12, 14, 17) — 1 commit bucket

Mỗi item: xóa file/thư mục → `python3 -m pytest tests/ -q --tb=no` full suite → normalized fail-set diff vs baseline = 0 new failures. Vì đây là deletions thuần, kỳ vọng: **passed giảm đúng bằng số test nằm trong file bị xóa, failed giữ 223**.

- [ ] **P1.1 Item 10** — `git rm src/api/polar_webhook.py.legacy tests/api/test_polar_webhook.py.legacy`
  - Bằng chứng dead: grep `polar_webhook` — chỉ còn comments LEGACY và tên log-file không liên quan; `.legacy` không import được
  - Tests cập nhật: không (test .legacy bị xóa cùng, pytest vốn không collect)
- [ ] **P1.2 Item 11** — `git rm -r src/old/`
  - Bằng chứng dead: 0 imports `from old` / `src.old`; test a2ui dùng `src.a2ui`
  - Tests cập nhật: không
- [ ] **P1.3 Item 12** — `git rm -r src/core/founder_vc src/core/founder_ipo`
  - Bằng chứng dead: docstring-only (212/223 bytes), 0 references
  - Tests cập nhật: không
- [ ] **P1.4 Item 14** — `git rm -r src/harness/sops-engine src/harness/observability/raas_auth`
  - Bằng chứng dead: sops-engine = license-only stub 125 bytes; raas_auth stub `authenticate()->False`, mọi consumer dùng `src.core.raas_auth` (19 import sites verified)
  - Kiểm tra thêm khi execute: `src/harness/__init__.py` và `src/harness/observability/__init__.py` không import 2 target này (đã đọc — observability init import telemetry_collector/tracing/metrics/health_reporter, không đụng raas_auth)
  - Tests cập nhật: không
- [ ] **P1.5 Item 17** — `git rm workflows/scripts/zenos-full-redesign-wf_6f2b5978-3f8.js` (+ rmdir `workflows/scripts/` nếu trống)
  - Bằng chứng dead: artifact wf_6f2b5978, chỉ nhắc trong journal 2025-06-18; 0 refs trong CI/config
  - Tests cập nhật: không
- [ ] **P1.6 Commit bucket 1**: `chore: remove audit-verified dead files (legacy polar webhook, src/old, empty shells, stub packages, zenos artifact)`
  - Pre-commit gates: `python3 -m ruff check src/ tests/` clean; full pytest parity
  - Agent: **fullstack-developer** (execute) → **tester** (parity verify)

### Phase 2 — Deletion có sửa code kèm theo (items 13, 15, 16)

- [ ] **P2.1 Item 13a** — `git rm src/daemon/llm_router.py` (0 importers verified)
- [ ] **P2.2 Item 13b** — `git rm src/daemon/llm_config.py` + sửa `src/daemon/executor.py`: xóa import `ModelConfig` (line 21) và method `run_llm()` (~line 87) — hàm dead (0 callers), là consumer DUY NHẤT của llm_config
  - Bằng chứng: grep `run_llm` toàn src+tests = 0 call sites; grep `daemon.llm_router` = 0
  - Tests cập nhật: `tests/daemon/test_mission_control.py` mock executor nhưng không đụng run_llm (41 tests đang pass — verify lại sau sửa)
- [ ] **P2.3 Item 15** — `git rm src/core/tracing.py tests/test_tracing.py`
  - Bằng chứng dead (prod): 0 production importers; duy nhất test file import
  - Tests cập nhật: xóa luôn test file (21 tests biến mất khỏi passed count — GHI RÕ trong ship report để giải thích delta passed)
- [ ] **P2.4 Item 16** — xóa `setup_telemetry` khỏi `src/core/telemetry/sdk_setup.py`; đồng thời dọn re-export tại `src/core/telemetry/__init__.py` (:18 import, :58 `__all__`). Nếu sau đó `sdk_setup.py` chỉ còn docstring/dead helper → `git rm` cả file
  - Bằng chứng dead: 0 call sites (duy nhất re-export); gateway dùng `telemetry_init.py`
  - ⚠️ Khi execute PHẢI verify `observe_agent` và các symbol khác trong `sdk_setup.py`/`telemetry/__init__.py` có consumer riêng trước khi quyết xóa cả file — nếu có thì chỉ xóa function `setup_telemetry`
- [ ] **P2.5 Commit bucket 2**: `refactor: remove dead daemon llm router/config, test-only tracing module, unused setup_telemetry`
  - Pre-commit gates: ruff clean; full pytest parity (failed=223 exact; passed giảm ~21 do test_tracing)
  - Agent: **fullstack-developer** → **tester**

### Phase 3 — KEEP-flagged decisions (item 18)

- [ ] **P3.1 Fold root `cli/tui/streaming.py` vào `src/cli/tui/`**
  - Move `cli/theme.py` → `src/cli/tui/theme.py`; move `cli/tui/streaming.py` → `src/cli/tui/streaming.py`
  - Sửa internal imports trong streaming.py: `from cli.theme import get_theme` → `from src.cli.tui.theme import get_theme` (hoặc relative import — chọn theo pattern sẵn có trong `src/cli/tui/router.py`)
  - Sửa `tests/test_tui_streaming.py:23`: `from cli.tui.streaming import` → `from src.cli.tui.streaming import`
  - Acceptance: 39 tests test_tui_streaming vẫn pass; `python3 -c "import cli.tui.streaming"` FAIL (module cũ biến mất); ruff clean
- [ ] **P3.2 Register 3 Typer apps** vào `src/cli/app_setup.py`: `billing` (billing_commands.app), `pev` (pev_commands.pev_app), `usage` (usage_commands.app)
  - Dry-run đã verified tại HEAD: build_app() + 3 add_typer → 36 groups, 0 duplicate names, 0 exception
  - Đã grep: KHÔNG có test assert command/group count cứng (không có rủi ro "33→36 breaks assertion")
  - Tests cập nhật: thêm 1 test nhỏ asserting 3 groups xuất hiện trong `build_app().registered_groups` (real behavior, không mock) — đặt tại `tests/test_wave3_surface.py` hoặc mở rộng file app_setup test có sẵn
- [ ] **P3.3 Escrow** — quyết định số phận phần còn lại của root `cli/` (`cli/commands/*` 9 files, `docs.py`, `strategy.py`, `developer.py`, `ui/`): duy nhất consumer là `tests/benchmark_cli.py` (standalone script, không collect). Ghi vào ship-report mục Escrow, KHÔNG xóa trong wave này
- [ ] **P3.4 Commit bucket 3**: `feat: register billing/pev/usage typer apps, fold tui streaming into src/cli/tui`
  - Agent: **fullstack-developer** → **tester**

### Phase 4 — Docs sync

- [ ] **P4.1** Cập nhật `docs/architecture/ARCHITECTURE_ASSESSMENT.md`: đánh dấu items 10–18 DONE (giữ nguyên văn bằng chứng verify, gồm note claim-stale của item 13); chuyển các row tương ứng trong bảng Deprecate/Delete sang trạng thái done
- [ ] **P4.2** Cập nhật `docs/architecture/DEPENDENCY_MAP.md` / `DEPRECATION_MAP.md` nếu có đề cập các file vừa xóa (grep trước khi sửa)
- [ ] **P4.3** Commit: `docs: mark wave 3 dead-code deletions complete in architecture assessment`
  - Agent: **docs-manager**

---

## 3. Risks & Gates

### Hard gates (mọi commit phải qua)

| Gate | Command | Ngưỡng |
|------|---------|--------|
| Parity | `python3 -m pytest tests/ -q --tb=no` | failed == 223 EXACT; normalized fail-set diff vs frozen baseline = 0 new failures (so tên test, không so số tuyệt đối — passed sẽ giảm hợp lệ ~21 do xóa test_tracing.py, tăng vài unit mới ở P3.2) |
| Fail-set normalize | sort + diff `failed_tests_*.txt` | 0 dòng FAILED mới; các dòng mất đi CHỈ được phép thuộc `tests/test_tracing.py` |
| Ruff | `python3 -m ruff check src/ tests/` | All checks passed |
| Protected flows | grep + import check | `src/raas/nowpayments_router.py`, `src/gateway.py:34,109`, `src/middleware/license_gate.py`, `src/lib/raas_gate/` — không file nào nằm trong deletion set (verified: 0 giao nhau) |

### Risks cụ thể

1. **Item 13 claim stale** (đã phát hiện): audit nói llm_config zero importers nhưng executor import ModelConfig. Mitigation: xóa cùng lúc run_llm + import (cặp dead-code). Nếu reviewer/gate thấy diff executor quá rối → escrow P2.2, giữ llm_config.py, chỉ xóa llm_router.py.
2. **Delta "passed" âm dễ gây hiểu nhầm gate**: xóa test_tracing.py làm passed giảm 21. Gate parity PHẢI đọc theo fail-set normalized, không theo tổng passed. Ship report phải liệt kê expected-delta trước khi chạy.
3. **Item 16 xóa nhầm symbol sống**: `telemetry/__init__.py` re-export nhiều thứ. Chỉ đụng `setup_telemetry`; verify từng symbol còn lại có consumer.
4. **P3.1 move file chạm import graph CLI**: streaming.py phụ thuộc theme + event_bus (`src.core.event_bus` — không đổi). Risk thấp vì chỉ test consumer. Nếu `src.cli.tui.router` hoặc ai đó ngầm import `cli.theme` → grep bắt được trước khi move.
5. **CI đỏ có sẵn KHÔNG phải blocker**: acceptance CI = gate set giống hệt 2 merge trước (10 đỏ + Security Hardening xanh tại `9b61cf3d7`/`0365918f5`). Một gate TRỞ LẠI xanh là tốt; một gate MỚI đỏ hoặc Security Hardening chuyển đỏ là blocker.
6. **Không đụng protected flows**: NOWPayments IPN chain (`src/raas/nowpayments_*`, `src/api/billing_routes.py` — lưu ý billing_routes KHÁCH với billing_commands), license gate (`src/middleware/license_gate.py`, `src/lib/raas_gate/`). Deletion set đã cross-check = 0 giao nhau.

---

## 4. Agents per step

| Phase | Step | Agent |
|-------|------|-------|
| P0 | push + CI verify + branch | git-manager (push), tester (gate-set verify) |
| P1 | zero-importer deletions + commit | fullstack-developer (execute), tester (parity) |
| P2 | deletions with code edits + commit | fullstack-developer (execute), tester (parity), debugger (nếu import error sau xóa) |
| P3 | registration + fold + new test | fullstack-developer (execute), tester (new test + parity) |
| P4 | docs update | docs-manager |
| Ship | PR + CI verify + merge + post-merge smoke | git-manager (PR/merge), tester (post-merge), suntzu-style verdict ghi vào result-verdict.md |

---

## 5. Ship Plan

### Pre-deploy checklist (trên branch feat/wave3-dead-code)

1. `python3 -m ruff check src/ tests/` → All checks passed
2. `python3 -m pytest tests/ -q --tb=no` → ghi received counts; tạo `failed_tests_wave3_local.txt` từ output
3. Normalize diff: `diff <(sort failed_tests_wave3_local.txt) <(sort .orchestrate/archive/audit-refresh-7459010db/failed_tests_head_0878f966f.txt)` → các dòng removed CHỈ từ test_tracing.py; 0 added
4. Import smoke: `python3 -c "import src.daemon.executor; import src.gateway; import src.main"` (gateway + main import được = protected flows & CLI entry còn nguyên)
5. CLI smoke: `python3 -m src.main --help` hiển thị billing/pev/usage groups; `python3 -c "from src.cli.app_setup import build_app; a=build_app(); print(len(a.registered_groups))"` → 36

### Commits (conventional, theo bucket)

1. `chore: remove audit-verified dead files (legacy polar webhook, src/old, empty shells, stub packages, zenos artifact)`
2. `refactor: remove dead daemon llm router/config, test-only tracing module, unused setup_telemetry`
3. `feat: register billing/pev/usage typer apps, fold tui streaming into src/cli/tui`
4. `test: assert registered billing/pev/usage groups on built app` (có thể gộp vào 3)
5. `docs: mark wave 3 dead-code deletions complete in architecture assessment`

### PR flow

1. Push branch `feat/wave3-dead-code` → `gh pr create` (title: `Wave 3: audit-verified dead-code deletion (assessment items 10-18)`), body theo mẫu `pr-body.md` (liệt kê từng item + bằng chứng + expected test deltas)
2. CI trên PR: chấp nhận cùng known-red set như 2 merge trước; Security Hardening phải xanh
3. Merge: squash (`gh pr merge --squash`) — pattern giống PR #3/#4/#5
4. Post-merge verify:
   - `gh run list --branch main --limit 12` → gate set == baseline set (không gate mới)
   - Full suite trên main mới: parity như pre-deploy checklist
   - `python3 -m src.main --help` → billing/pev/usage visible
   - Import check như trên

### Rollback readiness

- Deletions thuần: rollback = `git revert <squash-sha>` (single commit, không migration, không state ngoài git) — RPO = 0
- Không có DB/schema/deploy side-effect (CLI/library repo)
- Nếu post-merge phát hiện hidden importer (ImportError ở user machine): revert ngay; item gây lỗi được tách lại thành PR riêng với import shim deprecation thay vì hard delete
- Branch và PR giữ nguyên sau merge ít nhất đến khi archive xong

### Archive artifacts (sau merge)

1. `mkdir -p .orchestrate/archive/wave3-dead-code-<merge-sha>` ; `cp .orchestrate/latest/{plan.md,execution.md,result-verdict.md,plan-verdict.md,ship-report.md,pr-body.md,task.md} ...`
2. Copy `failed_tests_wave3_local.txt` vào archive làm bằng chứng parity
3. Update `.orchestrate/latest/task.md` → task kế tiếp hoặc đánh dấu done
4. Commit: `docs(orchestrate): archive wave 3 dead-code pipeline artifacts` → push thẳng main (pattern đã dùng cho f0f210de1)

---

## 6. Escrow Candidates (cut-scope nếu gate cần)

| Item | Điều kiện escrow | Cách escrow |
|------|------------------|-------------|
| **P2.2 (llm_config + executor.run_llm)** | Diff executor gây tranh cãi ở review, hoặc test nào bất ngờ chạm ModelConfig từ daemon path | Giữ `src/daemon/llm_config.py`; chỉ xóa `llm_router.py` (P2.1 vẫn chạy). Ghi follow-up |
| **P2.4 (setup_telemetry partial-file surgery)** | Phát hiện symbol khác trong sdk_setup có consumer (verify khi execute) | Chỉ xóa re-export lines, giữ file; hoặc bỏ whole item 16 |
| **P3.1 (fold streaming)** | Move làm nổ import nào ngoài dự kiến (theme được import ngầm nơi khác) | Bỏ fold, giữ nguyên root cli/tui/streaming.py + test — zero regression risk, chỉ là nợ đã được flag trong assessment |
| **P3.2 (register 3 apps)** | Register làm đỏ test surface nào không lường trước (đã dry-run sạch, risk rất thấp) | Tách thành PR riêng sau khi bucket 1+2 merged |
| **Root `cli/` còn lại (ngoài scope item 18)** | Luôn escrow — quyết định product-level (benchmark script + 9 command modules) | Ghi vào ship-report, không action trong wave này |

Escrow KHÔNG chặn merge: buckets còn lại tự đứng vững vì mỗi bucket là 1 commit độc lập có parity riêng.

---

## Assumptions

- **(high)** `f0f210de1` docs-only an toàn push thẳng main — verified: 36 files, toàn bộ `.orchestrate/**` markdown/txt.
- **(high)** Baseline fail-set 223 dòng tại `.orchestrate/archive/audit-refresh-7459010db/failed_tests_head_0878f966f.txt` vẫn là chuẩn đối chiếu — Wave 2 ship-report xác nhận "normalized diff = 0" với chính file này.
- **(medium)** Số passed sau wave ≈ 7576 − 21 (test_tracing) − 39 (test_tui_streaming di chuyển nhưng vẫn pass nên KHÔNG giảm) + vài test mới P3.2 → expect ≥ 7555, failed = 223 exact. Sai lệch hướng này ⇒ điều tra trước merge.
- **(medium)** Item 16: `sdk_setup.py` có thể chứa helper khác còn sống — plan đã buộc verify-per-symbol khi execute thay vì xóa mù cả file.
- **(low)** Không ai ngoài tests/benchmark_cli.py import root `cli/` — đã grep; nếu sai thì escrow P3.1 tự động áp dụng.
