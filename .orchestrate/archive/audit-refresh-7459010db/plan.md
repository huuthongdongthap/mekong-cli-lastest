# Plan: Architecture Audit — Mekong CLI → Autonomous Runtime (Refresh & Re-Verify)

Run: `.orchestrate/latest/` · Date: 2026-08-23 · Phase: PLAN (Kongming)
Work context: `/Users/macbook/mekong-cli` · HEAD: `0878f966f` (main, clean except `.orchestrate` tracking files)

---

## TL;DR

The audit the task describes **was already executed** (2026-08-17 → 2026-08-21): all six
deliverables exist in `docs/architecture/`, 11/11 AUTONOMY_GAPS closed, LLM/memory/agent-registry
wraps done. Since then **61 commits landed**, culminating in PR #2 (`0878f966f`, merged today) which
**deleted 142 files / −29,252 lines** — including modules the audit docs still list as live
(`billing_core.py`, `polar_webhook_handler.py`, `telemetry_hooks.py`, `billing_reconciliation.py`,
`quota_checker_service.py`, …) — and added an entirely unmapped subsystem (`src/design_intelligence/`).
The correct execution of this task is therefore a **refresh audit**: reconcile the six audit documents
against the current tree, re-trace the 10 execution paths, re-score, and re-derive the file-level
implementation order + smallest v0.1 Buzz path. **Zero production-code changes. STOP after the audit.**

---

## 1. Reframed Problem

**Original request (verbatim intent):** repo-wide architecture audit of Mekong CLI, map the listed
surfaces first, trace 10 execution paths, identify 13 problem categories, produce 6 documents,
score architecture/autonomy/production-readiness, give top-10 risks, top-10 ROI, file-level order,
reuse/wrap/deprecate lists, and the smallest v0.1 path to Buzz + Mekong = Autonomous Runtime.
Hard constraints: no rewrite, no parallel architecture, no speculative features, no deletion of
working functionality, **do not modify production code**, **STOP after the audit**.

**What is actually true now (scout evidence):**

| Fact | Evidence |
|------|----------|
| All 6 deliverables already exist | `docs/architecture/{CURRENT_ARCHITECTURE, DEPENDENCY_MAP, DUPLICATION_MAP, DEPRECATION_MAP, AUTONOMY_GAPS, MEKONG_CORE_CONTRACT}.md` + `ARCHITECTURE_ASSESSMENT.md` (scores 68/42/71) |
| Audit docs last updated 2026-08-17 → 2026-08-21 | `git log` on `docs/architecture/` |
| 61 commits since 2026-08-17 | `git log --since=2026-08-17 \| wc -l` = 61 |
| AUTONOMY_GAPS: 11/11 closed | `AUTONOMY_GAPS.md` summary; `buzz_adapter.py` (70 lines, 3 methods), `runtime_adapter.py:133-170` (mission tracer), governance `ActionClass`, cost guard commits `9dc6c6237`, `850f25acc` |
| LLM routing wrapped | `DEPRECATION_MAP.md` #2 WRAPPED 2026-08-21; `DUPLICATION_MAP.md` #5 RESOLVED |
| PR #2 deleted 142 files, −29,252 lines | `git diff --name-status 0878f966f^ 0878f966f` |
| Audit docs now reference **deleted** modules | `billing_core.py` cited in `ARCHITECTURE_ASSESSMENT.md:83`, `DEPENDENCY_MAP.md:44`, `DUPLICATION_MAP.md:29` — file no longer exists |
| New unmapped subsystem | `src/design_intelligence/` (schemas, gates, pipeline, design_memory, knowledge/) — zero mentions in any audit doc |
| `src/core/orchestrator.py` claim stale | CURRENT_ARCHITECTURE calls it "isolated / may be dead code"; it is now a live **package** `src/core/orchestrator/` (runner, step_executor, models, rollback, agi) imported by `agi_score.py:153`, `telegram_handlers.py:15,254`, `telegram_bot/formatters.py:13` |
| Legacy residue for deprecation review | `src/api/polar_webhook.py.legacy` (17 KB, Jul 4), `src/old/` dir, dual `src/mekong/` vs `src/mekongcli/` packages |
| Core contract state | `protocols.py` = 252 lines, 11 core Protocols + 9 supporting types; `GoalEngine` still **no implementation**; capability adapters filesystem/shell/browser/Cloudflare still missing; `settle_payment` still stub |
| Task's read-list dir `cloudflare-skills/` does not exist | `ls` fails; nearest equivalents: `recipes/cloudflare/`, `workflows/`, `.ci/` |
| CI doctrine | `.github/workflows/gates.yml` G1 (ruff+pyright+pytest+TS) → G2 security → G3 coverage ≥70% → G4 deps → G5 deploy-ready; `deploy.yml` is a separate Docker/K8s pipeline; dashboard deploys via `scripts/deploy-dashboard.sh` to CF Pages (GO_LIVE_PLAYBOOK.md) |
| Test baseline is NOT zero-failure | PR #2 body: "7533 passed, only pre-existing failures in 5 untouched files"; earlier ship report: 1 pre-existing network failure |

**Reframed decision:** This is not a greenfield audit — it is **audit maintenance at a forced
checkpoint**: the tree changed by ~30k lines under the audit docs. Deliverable = the same six
documents, updated to be *true at HEAD `0878f966f`*, plus re-derived scores/order/v0.1 path.
A from-scratch re-audit would duplicate work the repo's own contract (DRY, single source of truth)
forbids; a no-op "audit already done" reply would ship documents that cite deleted files.

**Goals:** (1) six docs 100% consistent with current tree; (2) honest re-scores with deltas;
(3) verified answer to "did PR #2's deletion sweep break any funnel or any closed autonomy gap?";
(4) refreshed file-level order + smallest v0.1 Buzz path.
**Non-goals:** any `src/` change, fixing what the audit finds (report only), new features,
Buzz/MCP/x402 implementation.

---

## 2. Work Checklist

### Step 0 — Freeze baseline
**Agent:** tester
- Record `git rev-parse HEAD` (`0878f966f`), `git status` (must show only `.orchestrate` drift).
- Run `python3 -m pytest tests/ -q` → capture pass/fail/skip counts as **BASELINE** (expect ~7533 passed + a small set of pre-existing failures; record the exact failing test IDs).
- Run `python3 -m ruff check src/ tests/` → record result.
**Acceptance:** baseline numbers written into execution report; failing-test ID list saved for later parity comparison.

### Step 1 — Map the mandated surfaces
**Agent:** Explore (broad scan)
- Read/map: `AGENTS.md`, `CLAUDE.md`, `HARNESS.md`, `README.md`, `dna/`, `agents/` (registry.yaml),
  `src/harness/` (core, pev, orchestration, agents, learning_loop, sops-engine, observability, evals),
  `engine/` (billing, license, payments), `factory/contracts/`, `src/cli/`, `integrations/` (zalo.py),
  `recipes/cloudflare/`, `workflows/`, `observability/`, `specs/`, `tests/`.
- `cloudflare-skills/` does not exist — record as deviation, cover via `recipes/cloudflare/` + `.ci/` + `workflows/`.
**Acceptance:** one surface table (path → purpose → entry points → live/dead verdict) in scout report; every mandated path accounted for or explicitly marked missing.

### Step 2 — Reconcile audit docs vs current tree (drift sweep)
**Agent:** Explore + docs-manager
- Extract every file/module path cited in the six docs + `ARCHITECTURE_ASSESSMENT.md`; verify each exists at HEAD.
- Known stale hits to confirm and fix: `src/raas/billing_core.py`, `src/raas/polar_webhook_handler.py`, `src/core/telemetry_hooks.py`, `src/raas/billing_reconciliation.py`, `src/raas/quota_checker_service.py`, `src/raas/billing_alert_service.py`, `src/raas/workspace_repository.py`, `src/lib/raas_gate/license_gate_core.py`, `src/cli/command_registry_legacy.py`, `src/cli/slash_commands.py`, `src/cli/auto_updater.py`, `src/cli/roi_commands.py`, `src/cli/roi_usage.py`, `src/core/founder_vc/*`, `src/harness/core/plan_constraints.py`.
- For each: mark **DELETED in PR #2** (with commit) or update the claim.
**Acceptance:** zero doc references to nonexistent files (mechanical grep check passes — see Gate G-DOCS).

### Step 3 — Re-trace the 10 execution paths
**Agent:** Explore (2 parallel forks: paths 1–5, paths 6–10)
1. CLI entrypoint (`src/main.py` → Click) 2. command dispatch (`src/commands/` + `commands_registry.py`, 43 cmds)
3. harness (`src/harness/`) 4. PEV (`src/harness/pev/`) 5. agent registry (`src/core/agent_registry.py`)
6. LLM router (`llm_router_adapter.py` → `llm_client.py`; daemon `src/daemon/llm_router.py` separate)
7. tool execution (`capability.py`, `mcp_capability_adapter.py`) 8. verification (`verifier.py`)
9. observability (`src/telemetry/` — now only `rate_limit_metrics.py`; check where mission tracing went after `telemetry_hooks.py` deletion) 10. billing/payment (`mcu_billing.py`, `billing_adapter.py`, `src/raas/nowpayments_*`, `src/api/billing_routes.py`, `src/services/polar_client.py` + `src/api/webhooks/router.py` after `polar_webhook_handler.py` deletion).
**Acceptance:** each path = caller chain with `file:line`; any **broken/orphaned** path (especially #9 and #10 post-deletions) flagged as a finding with severity.

### Step 4 — Re-assess the 13 problem categories on the post-PR#2 tree
**Agent:** Explore + researcher (external only if needed for Buzz/MCP/x402 current specs)
- Special focus items the old audit cannot answer:
  a. Did the 142-file deletion sweep orphan any business funnel (Zalo OA / tax-accounting / Sophia video) or any CLI command still advertised in README/CLAUDE.md?
  b. Is `src/design_intelligence/` contract-compliant (imports core Protocols, uses `MemoryStore` `design:` namespace, advisory-only deploy hook) — map it into CURRENT_ARCHITECTURE.
  c. Did any closed autonomy gap regress (e.g., mission observability after `telemetry_hooks.py` deletion; license gate after `license_gate_core.py` deletion)?
  d. New deprecation candidates: `src/api/polar_webhook.py.legacy`, `src/old/`, `src/mekong/` vs `src/mekongcli/` overlap.
**Acceptance:** each of the 13 categories has a current-status entry with evidence; every regression flagged (report-only — no fixes).

### Step 5 — Update `CURRENT_ARCHITECTURE.md`
**Agent:** docs-manager
- Fix layer structure: orchestrator is a live package; telemetry shrunk; `design_intelligence/` added; deleted raas/cli modules removed; test/file counts at HEAD.
**Acceptance:** layer diagram matches `ls src/`; counts verified; no stale module names.

### Step 6 — Update `DEPENDENCY_MAP.md`
**Agent:** docs-manager
- Remove deleted modules; fix orchestrator "orphaned" row (now live, list importers); re-verify `src/forest/`, `src/studio/`, `src/strategies/polymarket/` status; external deps unchanged check.
**Acceptance:** orphan table accurate at HEAD; every row grep-verifiable.

### Step 7 — Update `DUPLICATION_MAP.md`
**Agent:** docs-manager
- Billing: re-count after `billing_core.py` deletion (was 8+; verify survivors: `mcu_billing`, `raas/billing_engine`, `raas/billing`, `raas/billing_{proration,idempotency,audit,sync,event_emitter}`, `api/billing_routes`, `api/raas_billing_service`, `api/vn_pilot_billing`, `api/vn_payments_routes`); keep #5 LLM RESOLVED; verify #7 four billing routes still all live (confirmed present at HEAD).
**Acceptance:** every module in every table exists at HEAD; statuses current-dated.

### Step 8 — Update `DEPRECATION_MAP.md`
**Agent:** docs-manager
- Mark items resolved-by-deletion; add new candidates with risk ratings: `polar_webhook.py.legacy` (LOW), `src/old/` (LOW), `mekong`/`mekongcli` package overlap (needs Step 4b verdict first), deferred items #3/#5 re-verified.
**Acceptance:** each candidate has status + migration path + risk; nothing listed as live that is gone.

### Step 9 — Re-verify `AUTONOMY_GAPS.md` at HEAD
**Agent:** docs-manager + tester (spot-check by running targeted tests)
- Verify each of the 11 closed gaps is still closed **in current code**: `buzz_adapter.py` 3 methods; approval gate in `runtime_adapter.execute()`; cost guard; retry limit; memory ownership; capability ownership/expiry; mission tracer (`runtime_adapter.py:155-170`); cost-in-telemetry. Flag any closure that depended on a deleted file.
**Acceptance:** 11/11 re-confirmed or regressions listed with file evidence; summary table updated with verification date.

### Step 10 — Update `MEKONG_CORE_CONTRACT.md`
**Agent:** docs-manager
- Protocol table: 11 core Protocols at `protocols.py` line numbers (verified: MekongCoreRuntime:123, LLMRouter:140, ToolRegistry:153, BillingMeter:163, MemoryStore:172, ObservabilitySink:182, VerificationEngine:190, GoalEngine:198, PaymentProvider:207, CapabilityBus, SerializableBillingResult:216).
- Keep honest: `GoalEngine` ❌ no implementation; capability adapters filesystem/shell/browser/Cloudflare ❌ missing; x402/MPP settle stubs.
**Acceptance:** every Protocol row has correct `file:line`; implementation-status column matches HEAD.

### Step 11 — Re-score in `ARCHITECTURE_ASSESSMENT.md`
**Agent:** docs-manager (numbers proposed), suntzu (challenge)
- Re-score architecture/autonomy/production-readiness /100 with **delta vs 68/42/71 and evidence per point moved** (upward pressure: 11/11 gaps closed, LLM wrap, −29k-line cleanup, design-intelligence contract compliance; downward pressure: any regression found in Steps 3–4, still-missing GoalEngine/capability adapters, deferred billing consolidation, pre-existing test failures).
- Refresh: top-10 risks, top-10 ROI, exact file-level implementation order, reuse/wrap/deprecate lists, **smallest v0.1 path to Buzz + Mekong = Autonomous Runtime** (expected shape: BuzzAdapter already exists → wire `run_from_payload` end-to-end + one real capability adapter + settle_payment un-stub; must be derived from evidence, not assumed).
**Acceptance:** each score has a rationale table; every risk/ROI item traceable to a Step 2–4 finding; v0.1 path lists concrete existing files to reuse.

### Step 12 — Consistency gate (mechanical)
**Agent:** tester
- Script: extract all `src/**`, `tests/**`, `engine/**`, `factory/**` paths from the seven docs; assert each exists at HEAD. Diff doc cross-references.
**Acceptance:** Gate G-DOCS passes (zero dangling references); inconsistency list empty.

### Step 13 — Full-suite parity check
**Agent:** tester
- `python3 -m ruff check src/ tests/` and `python3 -m pytest tests/ -q`; compare against Step 0 BASELINE.
**Acceptance:** Gate G-TEST passes — identical pass/fail set; any new failure blocks ship (docs-only change cannot legitimately move tests).

### Step 14 — Ship (see section 5)
**Agent:** git-manager, then suntzu (result verdict), then docs-manager (ops journal).

---

## 3. Risks & Gates

| # | Risk | Sev | Mitigation / Gate |
|---|------|-----|-------------------|
| R1 | Marking a live module dead (or vice versa) during drift sweep | HIGH | Every deleted/dead verdict requires two proofs: file absent at HEAD **and** zero importers via grep + `git log` for the deleting commit. No verdict from memory. |
| R2 | PR #2 deletion sweep silently broke a funnel or a closed autonomy gap | HIGH | Steps 3 (#9, #10) and 4a/4c trace exactly this; findings go into top-10 risks. **Report-only** — fixing is out of scope and would violate the task's no-code constraint. |
| R3 | Scope creep into implementation ("small fix while we're here") | HIGH | **Gate G-SCOPE:** `git diff --name-only` of the run must match `docs/architecture/*.md` (+ `.orchestrate/`, changelog) only. Any `src/` hit = AMEND. |
| R4 | CI red from pre-existing failures misread as regression | MED | Step 0 freezes the failing-test ID list; Gate G-TEST is *parity with baseline*, not zero failures (repo doctrine: PR #2 merged with 5 known-failing untouched files). |
| R5 | Score bias (inflating because "we did 61 commits") | MED | Step 11 requires per-point delta evidence; suntzu challenges scores before publish. |
| R6 | Task read-list references nonexistent dirs (`cloudflare-skills/`) | LOW | Recorded as deviation in Step 1; nearest real surfaces mapped instead. Assumption A3. |
| R7 | Docs-only PR still runs heavy G1–G5 gates; G5 CF dry-run may flake | LOW | If a gate fails for infra reasons unrelated to the diff, capture evidence and re-run once; document in ship report. |
| R8 | Stale `.orchestrate` deletions in working tree confuse the run | LOW | Those are prior-run tracking files already archived; the run writes fresh `plan.md`/`execution.md` set; commit only intended paths. |

**Gates summary:** G-SCOPE (docs-only diff) · G-DOCS (zero dangling file refs) · G-TEST (baseline parity) · G-VERIFY (suntzu PASS on result).

---

## 4. Agent đề xuất cho từng bước (Agent assignments)

| Step | Agent | Why |
|------|-------|-----|
| 0, 12, 13 | `tester` | Mechanical baselines and gates; no judgment needed |
| 1, 3 (×2 parallel), 4 | `Explore` | Read-only wide scans; paths 1–5 and 6–10 run as two parallel Explore forks to halve wall time |
| 2 | `Explore` → `docs-manager` | Detect drift, then apply doc edits |
| 4 (external) | `researcher` | Only if current Buzz/MCP/x402 specs are needed to judge "missing interfaces" — keep minimal |
| 5–11 | `docs-manager` | All doc updates; one owner keeps voice/format consistent |
| 11 (challenge) | `suntzu` | Independent check on scores and top-10 lists before publish |
| 14 | `git-manager` → `suntzu` → `docs-manager` | Commit/PR/CI, result verdict, ops journal |
| Overall | orchestrator sequences; no `fullstack-developer`/`cto` needed — **no code changes in this run** |

---

## 5. Ship Plan (full chain)

### 5.1 Pre-deploy checklist
- [ ] `git status` — only `.orchestrate/` tracking files + the seven updated docs dirty; nothing in `src/`, `tests/`, `engine/`, `factory/`.
- [ ] `git diff --name-only` passes **G-SCOPE** (docs/architecture only).
- [ ] Step 12 mechanical check passes (**G-DOCS**): zero references to nonexistent files.
- [ ] `python3 -m ruff check src/ tests/` — unchanged from Step 0 baseline.
- [ ] `python3 -m pytest tests/ -q` — pass/fail set identical to Step 0 baseline (**G-TEST**).
- [ ] No secrets, tokens, or `.env` content quoted into any doc (grep `sk-`, `Bearer`, `PRIVATE_KEY` in diff).
- [ ] Scores have per-point delta evidence; v0.1 Buzz path lists real existing files.

### 5.2 Commit
- Branch: `docs/architecture-audit-refresh` from `main` (`0878f966f`).
- Commit 1: `docs(architecture): refresh audit documents for post-PR#2 tree` — the seven docs.
- Commit 2 (optional, separate): `docs: record architecture audit refresh in changelog` — `docs/project-changelog.md` (+ roadmap status line if phase tracking applies).
- Conventional format, no AI references, no plan/phase IDs in the message (stable-artifacts rule).

### 5.3 PR
- `gh pr create --repo minhlongs/mekong-cli --base main` — title `docs(architecture): refresh audit for post-PR#2 tree (scores, maps, v0.1 Buzz path)`.
- Body: score table old→new with one-line rationale each; count of stale references fixed; regressions found (if any); explicit statement "docs-only, zero source changes"; link the task. Body ends with the Generated-with footer.

### 5.4 CI verify
- `gh run list --branch docs/architecture-audit-refresh -L 1 --json status,conclusion`; watch gates G1–G5 in `gates.yml`.
- Pass criterion: all gates green, **or** any red gate proven pre-existing/infra by comparison with a `main` run at the same day (capture both run URLs as evidence).
- If red due to the diff: fix docs, re-push, re-verify. Never merge red.

### 5.5 Merge
- Squash-merge (repo convention per PR #2). Verify `main` HEAD advanced; working tree clean afterward.

### 5.6 Deploy theo doctrine repo
- Repo doctrine: runtime deploys are CF Pages dashboard (`scripts/deploy-dashboard.sh`, GO_LIVE_PLAYBOOK) and the Docker/K8s `deploy.yml` pipeline — both triggered by **app/source** changes.
- This change is **docs-only → no deploy is required and none is run.** State this explicitly in the ship report ("Deploy: skipped — docs-only diff, no source changes; doctrine deploys apply to app changes only"). This is the doctrine-correct action; deploying anyway would be cargo-cult risk for zero benefit.

### 5.7 Prod smoke
- Purpose: prove the CLI is byte-identical in behavior. Run: `mekong --version`, `mekong --help`, `mekong ui --help` (or `python3 -m src.main --help` if the binary isn't on PATH). Expected: same 43-command surface as before the merge. Any deviation = incident, not docs bug → investigate.

### 5.8 Feature smoke
- Not applicable (no feature shipped). Substitute: verify the seven docs render — open/diff them, confirm tables intact, no broken markdown, cross-links between the seven docs resolve.

### 5.9 Rollback readiness
- Rollback = `git revert <merge-sha>` of the docs commit; single-commit revert, zero data/state migration, no service impact.
- Previous doc state recoverable from history at `0878f966f`. No env vars, secrets, or configs touched. Rollback decision does not require deploy rollback (nothing was deployed).

### 5.10 Ops / journal
- Write `.orchestrate/latest/execution.md` (step log with evidence), `ship-report.md` (checklist results, commit SHAs, CI run URLs, smoke output), `result-verdict.md` (suntzu PASS/AMEND/FAIL on the delivered audit).
- Update `docs/project-changelog.md` entry: "Architecture audit refreshed at HEAD 0878f966f — scores X/Y/Z, N stale references fixed, regressions: …".
- Archive: copy the run folder to `.orchestrate/archive/20260823-architecture-audit-refresh/` per existing convention.

---

## What to Avoid

- **Do not re-audit from scratch** — the six docs are the repo's canonical audit surface; rewriting them in parallel violates the repo's own single-source-of-truth contract.
- **Do not fix anything found** — the task says STOP after the audit; a regression found in Step 4 is a *finding*, not a ticket to silently work.
- **Do not trust the old docs' module lists** — at least 15 cited files were deleted in PR #2; every claim re-verified at HEAD or it is wrong by construction.
- **Do not treat pre-existing test failures as blockers or as license to ignore new ones** — parity with the frozen baseline is the only correct bar.
- **Do not score from vibes** — every point of score movement needs a named file/commit.
- **Do not deploy** — docs-only; a deploy here is pure risk.

## Alternatives & Trade-offs

1. **From-scratch independent audit** (ignore existing docs, re-derive all six). Cost: ~2–3× effort, duplicates verified work, creates a second source of truth mid-flight. Rejected unless evidence shows existing docs are systematically wrong (they are stale, not wrong — drift-fix is cheaper and safer).
2. **Declare "audit already done", ship nothing.** Cost: the docs cite ≥15 deleted files and miss a whole subsystem; the next implementation phase would plan against fiction. Rejected.
3. **Audit + immediate micro-fixes** (delete `.legacy` file, patch broken imports found). Tempting; violates the explicit task constraint and the no-deletion-of-working-functionality rule until each item is proven dead. Rejected for this run; becomes the first entries of the refreshed implementation order instead.

## Success Metrics

- 0 dangling file references across the seven docs (mechanical check).
- 7/7 docs updated and dated at HEAD `0878f966f`.
- Scores re-published with per-point delta evidence; v0.1 Buzz path names concrete existing files (`buzz_adapter.py`, `runtime_adapter.py`, …).
- All 11 autonomy gaps re-verified or regressions explicitly listed.
- Test pass/fail set identical to baseline; ruff unchanged.
- Diff touches only `docs/architecture/` (+ changelog, `.orchestrate/`).
- suntzu result verdict: PASS.

## Assumptions

| # | Assumption | Conf | What would flip it |
|---|-----------|------|--------------------|
| A1 | This run is a **refresh** of the existing audit, not a from-scratch redo — because all six deliverables already exist and the task text is the original Phase-1 prompt replayed at a later checkpoint | HIGH | Caller explicitly wants an independent redo ignoring existing docs → Step 2 becomes re-derive-then-diff (+~1 day) |
| A2 | Task constraints remain binding: no production-code changes, STOP after audit | HIGH | Caller authorizes fixes → insert implementation phases after Step 14 |
| A3 | `cloudflare-skills/` in the read list is a stale name; real coverage = `recipes/cloudflare/` + `workflows/` + `.ci/` | MED | A `cloudflare-skills` dir exists elsewhere (e.g., under `apps/`) → map it too |
| A4 | PR #2's 142 deletions were an intentional dead-code sweep accompanying the Hallmark merge | MED | Evidence of accidental deletion (funnel broken, command missing) → that becomes top risk #1 and the v0.1 path is reprioritized around restoration |
| A5 | CI baseline contains a small set of pre-existing failures; pass bar = parity, not zero | HIGH | A fully green `main` run exists → pass bar becomes zero failures |
| A6 | Docs-only change requires no deploy under repo doctrine | HIGH | Doctrine doc appears mandating deploy on any merge → add CF Pages dry-run step |
