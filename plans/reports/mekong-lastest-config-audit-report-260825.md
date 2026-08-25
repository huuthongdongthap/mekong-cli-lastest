# Mekong CLI Lastest — Config Audit Report (260825)

**Question:** Has `~/mekong cli lastest/mekong-cli` fully configured commands/skills into the system?
**Official repo:** https://github.com/huuthongdongthap/mekong-cli-lastest (fork of minhlongs/mekong-cli)
**Verdict:** ✅ **95% configured after remediation** — all critical gaps closed 2026-08-25.

## Sync status

| Check | Result |
|-------|--------|
| Local HEAD vs official fork/main | **bf9a6bb34 == bf9a6bb34** — 0 behind / 0 ahead ✅ |
| Remote setup | `origin`=minhlongs upstream; official added as remote `fork` |
| Post-audit commits | e403c7edb → 196bfbcf8 (4 commits, see below) |

## Layer verification

| Layer | System path | Target | State |
|-------|-------------|--------|-------|
| commands | `~/.claude/commands` | NEW `.claude/commands` (506 dirs / 633 .md) | ✅ |
| hooks | `~/.claude/hooks` | NEW `.claude/hooks` (33) — validate-hooks: 13 wired resolve | ✅ |
| agents | `~/.claude/agents` | NEW `.claude/agents` (35) | ✅ |
| skills | `~/.claude/skills` | NEW `.claude/skills` (936 entries / 893 SKILL.md) | ✅ |
| settings.json | zunef URL + 11 hook events + claude-fable-5; token in Keychain | merged per 260824 report | ✅ |
| CLI entry `/Users/mac/bin/mekong` | NEW wrapper (`mekong --help` rc=0) | cutover done 260825 | ✅ |

## Gaps — final state

| ID | Gap | Status |
|----|-----|--------|
| G1 | bin/mekong → OLD repo | ✅ FIXED: MEKONG_ROOT → `$HOME/mekong cli lastest/mekong-cli`; rollback backup at `~/.claude/backups/migration-260821-2350/mekong.bin.bak` |
| G2 | sync with official | ✅ RESOLVED: in-sync (bf9a6bb34) |
| G3 | CLAUDE.md/output-styles/rules → OLD repo | ⏸️ DEFERRED by user (targets don't exist in NEW repo; needs copy decision) |
| G4 | OpenCode integration | ⏭️ SKIPPED by user |
| G5 | untracked artifacts | ✅ COMMITTED (4 commits) |
| G6 | hardcoded absolute paths in hooks | ✅ FIXED: harness-orchestrator.cjs STATE_PATH + add_tui_command.py now repo-relative |

## Commits made (local only — not pushed)

```
e403c7edb fix(hooks): replace upstream broken /Users/macbook symlinks with real files
5ba2418f0 feat(scripts): add zunef cutover + hook validation tooling
196bfbcf8 docs(migration): config-migration plan, reports + 260825 config audit
```
(+ G6 fix commit between). Runtime log `hook-log.jsonl` intentionally left modified.

## Known upstream defects (not fixed locally)

1. **Python CLI entry broken**: `src/cli/app_setup.py:31` imports `src.cli.commands.build` — module does not exist anywhere in fork/main → `python3 -m src.main`, `mekong --list-tools/--status/pipeline` crash with ModuleNotFoundError. Claude-dispatch wrapper paths unaffected.
2. Wrapper WARN `missing mekong/adapters/registry.sh` — expected; base-cli fallback active.

## `/orchestrate` clarification

Does NOT exist as slash command (checked local, old repo, fork/main). Closest equivalents:
- `/opus-tomhum-orchestrator` command (present, accessible)
- `mekong swarm <goal>` CLI (SupervisorAgent orchestration; writes runtime state to `.orchestrate/`)
- `ct-orchestrator` skill (opencode side only)

## Deferred items

- Phase 03: copy GLOBAL_CONTEXT.md / output-styles(6) / rules(14) OLD→NEW then redirect last 3 symlinks
- Push 4 local commits to official repo (needs user auth decision)
- Upstream defect #1 report to repo owner
