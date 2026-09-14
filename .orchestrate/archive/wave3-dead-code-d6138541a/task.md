# Task: Push pending commit + Wave 3 (Dead-code deletion)

**Ngày:** 2026-08-25
**Repo:** /Users/macbook/mekong-cli (branch: main, ahead origin/main 1 commit)
**Nguồn:** user chọn "1+2" từ đề xuất của orchestrator.

## Yêu cầu nguyên văn

1. **Push commit đang treo** — `f0f210de1` ("docs(orchestrate): archive wave 2 masked-import fixes pipeline artifacts") đang ahead origin/main 1 commit, chưa push. Cần push + verify CI.
2. **Wave 3 tiếp theo** — nối tiếp Wave 1 (PR #4, runtime safeguards) và Wave 2 (PR #5, masked imports). Cả 4 critical defects của Mekong Audit đã được fix xong trong Wave 1+2. Wave kế tiếp theo `docs/architecture/ARCHITECTURE_ASSESSMENT.md` (mục "File-Level Implementation Order") là **Wave 3 — Dead code (audit-verified deletions), items 10–18**.

## Bối cảnh đã xác minh

- 4 critical defects (report-only từ audit refresh PR #3):
  1. `mekong run` crash do `_NullTelemetry` thiếu emit() → **đã fix Wave 1 (PR #4)**
  2. MCP capability adapter import sai `MCPServer` → **đã fix Wave 1 (PR #4)**
  3. Daemon scheduler unsandboxed shell exec → **đã fix Wave 1 (PR #4)**
  4. Masked broken imports (command_fabric/router, implement/__init__, agi_bridge) → **đã fix Wave 2 (PR #5)**
- Wave 3 theo ARCHITECTURE_ASSESSMENT.md: dead-code deletion waves (items 10–18, chi tiết trong file).
- Baseline test parity (bắt buộc giữ nguyên): **223 failed / 7576 passed / 75 skipped** — normalized fail-set diff phải = 0 new failures so với frozen baseline.
- CI trên main đang đỏ do repo debt có sẵn (thiếu `pnpm-lock.yaml` làm gãy G1/G3/G4...) — KHÔNG phải regression; Security Hardening & Attestation gate vẫn xanh. Không được coi CI đỏ là blocker mới, nhưng phải verify đúng gate set giống các merge trước.
- Protected flows KHÔNG được đụng: NOWPayments IPN, license gate chain.
- Repo này là CLI/library (Python) — không có deploy production; "ship" = commit → PR → CI verify → merge. Smoke = chạy test + import check + CLI smoke.
- Commit `f0f210de1` là docs-only (archive pipeline artifacts), an toàn để push thẳng main.

## Ràng buộc

- Giữ exact test parity 223 failed (không thêm failure mới).
- Ruff clean.
- Không đụng protected flows.
- Mỗi deletion phải audit-verified (có bằng chứng dead code trước khi xóa).
- Pipeline artifacts ghi vào `.orchestrate/latest/` (sẽ được archive + commit sau khi ship).
