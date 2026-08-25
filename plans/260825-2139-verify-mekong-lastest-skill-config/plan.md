# Verify: mekong cli lastest — Command/Skill Config Audit

**Date:** 2026-08-25 | **Mode:** standard | **Type:** Verification + remediation plan

## Question
Has the new repo `~/mekong cli lastest/mekong-cli` fully configured its commands & skills into the system?

## UPDATE 2026-08-25 21:50 — Official repo confirmed
Official = **https://github.com/huuthongdongthap/mekong-cli-lastest** (fork of minhlongs/mekong-cli).
- Added as git remote `fork`. Verified: **local HEAD == fork/main == bf9a6bb34** (0 behind, 0 ahead). ✅ IN SYNC
- Earlier "10 commits behind" applied only to minhlongs/mekong-cli upstream — different lineage, not authoritative.
- `.orchestrate/` dir explained: runtime state workspace of `mekong swarm <goal>` CLI command (src/cli/commands/swarm_orchestration.py → run_swarm), containing task.md/plan.md/execution.md/ship-report.md. NOT a slash command.
- `/orchestrate` command does NOT exist anywhere (local, upstream, old repo). Closest: `/opus-tomhum-orchestrator` (command), `mekong swarm` (CLI), ct-orchestrator (opencode skill).
- **NEW gap G6:** `hooks/harness-orchestrator.cjs` + `hooks/lib/add_tui_command.py` hardcode OLD path `~/mekong-cli/.mekong/.harness-state.json`.

## Verdict: ✅ 85% configured — gaps G1, G3, G6 remain; G2 resolved (in sync with official)

Migration of 2026-08-24 (`plans/260821-2350-mekong-config-migration/`, report claims 25/25 passed) is holding. Union layer intact and growing.

## Audit results

### ✅ Verified working (system → NEW repo)

| Layer | System path | Target | State |
|-------|-------------|--------|-------|
| commands | `~/.claude/commands` | NEW `.claude/commands` (506 dirs / 633 .md) | OK |
| hooks | `~/.claude/hooks` | NEW `.claude/hooks` (33, validate-hooks.py: resolve OK) | OK |
| agents | `~/.claude/agents` | NEW `.claude/agents` (35) | OK |
| skills | `~/.claude/skills` | NEW `.claude/skills` (936 entries / 893 SKILL.md) | OK |
| settings.json | merged per report; zunef base URL; 11 hook events; model claude-fable-5 | — | OK |
| Stage B | zunef token present in Keychain (`mekong-zunef`) | cutover script exists | OK |

Counts grew since migration report (491→506 cmds, 27→33 hooks, 28→35 agents, 893 skills unchanged) — expected repo evolution.

### ⚠️ Gaps found

| # | Gap | Detail | Severity |
|---|-----|--------|----------|
| G1 | `/Users/mac/bin/mekong` wrapper still points to OLD repo (`MEKONG_ROOT=/Users/mac/mekong-cli`) | NEW repo ships its own `scripts/mekong-wrapper.sh`; CLI dispatch never uses it | HIGH |
| G2 | ~~New repo 10 commits behind~~ **RESOLVED**: in sync with official `huuthongdongthap/mekong-cli-lastest` (bf9a6bb34). Local `origin` points to minhlongs upstream; official added as remote `fork` | RESOLVED |
| G3 | `~/.claude/{CLAUDE.md,output-styles,rules}` still → OLD repo | MED |
| G4 | OpenCode integration absent — user chose SKIP (2026-08-25) | SKIPPED |
| G5 | Untracked artifacts in NEW repo: plans, cutover-zunef.sh, validate-hooks.py | LOW |
| G6 | Hooks hardcode OLD repo path: `harness-orchestrator.cjs` (STATE_PATH → ~/mekong-cli/.mekong/), `lib/add_tui_command.py` | MED |

Note: G3 symlinks must NOT be blindly redirected — targets don't exist in NEW repo. Options: copy OLD→NEW then redirect, or keep OLD as shared-content source (documented).

## Phases

- [x] **phase-01-pull-and-revalidate.md** — RESOLVED: verified in-sync with official fork (bf9a6bb34); hooks validate OK. No pull needed.
- [ ] **phase-02-mekong-bin-cutover.md** — Point `/Users/mac/bin/mekong` → NEW wrapper; keep OLD reachable via fallback flag/env
- [ ] **phase-03-shared-content-decision.md** — Decide CLAUDE.md/output-styles/rules: copy to NEW union layer vs keep OLD source-of-truth (needs user input)
- [x] **phase-04-opencode-integration.md** — SKIPPED by user decision
- [ ] **phase-05-commit-and-final-audit.md** — Commit artifacts, fix G6 hardcoded hook paths, full smoke test, write final report

## Rollback

All changes reversible via `~/.claude/backups/migration-260821-2350/` (untouched) + git reset in NEW repo.
