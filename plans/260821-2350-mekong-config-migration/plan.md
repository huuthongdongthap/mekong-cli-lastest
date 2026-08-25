# Mekong CLI Config Migration: OLD → NEW Structure

## Status
- [x] Read OLD system layout (symlinks, settings, hooks, commands, skills, agents)
- [x] Read NEW system layout (_core, _pipeline, _integration, _quality, _archive)
- [x] Map hook/command/skill/agent deltas
- [ ] Create migration plan
- [ ] Execute Phase 1: backup + symlink redirect
- [ ] Execute Phase 2: settings.json merge
- [ ] Execute Phase 3: hooks migration
- [ ] Execute Phase 4: commands/skills/agents dedup
- [ ] Execute Phase 5: validation + rollback prep

## Objective
Migrate the active Claude Code config from the OLD flat structure
(`~/.claude/` → `~/mekong-cli/.claude/`) to the NEW organized structure
(`/Users/mac/mekong cli lastest/mekong-cli/.claude/`).

## Key Insight
The OLD system uses **flat symlinks** (`~/.claude/commands → ~/mekong-cli/.claude/commands`).
The NEW system uses **purpose-layered directories** under `.claude/`:
`_core/`, `_pipeline/`, `_integration/`, `_quality/`, `_archive/`.
CC CLI only reads `.claude/commands/`, `.claude/hooks/`, `.claude/agents/`,
`.claude/skills/`, `.claude/settings.json`, `.claude/mcp.json`.

**Therefore the migration is a symlink-rewrite problem, not a copy problem.**
We keep the NEW repo as source of truth and re-point the OLD symlinks.

## Deliverables
- `phase-01-backup-symlink-redirect.md`
- `phase-02-settings-merge.md`
- `phase-03-hooks-migration.md`
- `phase-04-content-dedup.md`
- `phase-05-validation-rollback.md`

## Risk Summary
| Risk | Severity | Mitigation |
|------|----------|------------|
| Symlink break → CC CLI loses commands | HIGH | Atomic swap + pre-swap smoke test |
| Hook path mismatch → hooks silently skipped | HIGH | Validate every hook resolves to a real file |
| Settings merge loses user perms | MEDIUM | Diff before/after, keep old allow/deny lists |
| MCP env keys lost | MEDIUM | Copy `~/.claude/.mcp.json` + env from old settings |
| 466 commands → 119 commands loses coverage | MEDIUM | Map old→new, archive unmapped, log gaps |
| 896 skills → 34 skills loses domain coverage | MEDIUM | Keep OLD 867 domain skills, merge NEW 29 shared |

## Dependencies
- NEW repo at `/Users/mac/mekong cli lastest/mekong-cli/` (already cloned)
- OLD system at `~/.claude/` + `~/mekong-cli/.claude/` (already active)
- No network needed (all local)