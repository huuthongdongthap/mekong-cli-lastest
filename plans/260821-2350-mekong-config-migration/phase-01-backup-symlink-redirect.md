# Phase 01: Backup + Symlink Redirect

## Overview
Capture full state of OLD system, then atomically re-point the OLD symlinks
to the NEW repo. No content is deleted yet — only symlink targets change.

## Priority
P0 — blocking. Everything else depends on a known-good backup + redirect.

## Status
pending

## Pre-flight
```bash
# 1. Verify OLD system intact
ls -la ~/.claude/ | grep -E "commands|hooks|agents|skills|settings"
# Expected: 4 symlinks + settings.json

# 2. Verify NEW repo intact
ls /Users/mac/mekong\ cli\ lastest/mekong-cli/.claude/
# Expected: _core, _pipeline, _integration, _quality, _archive

# 3. Verify no active mekong-cli process
pgrep -f "mekong" || echo "no mekong process"
```

## Step 1.1 — Full backup
```bash
BACKUP=~/.claude/backups/migration-260821-2350
mkdir -p $BACKUP

# Symlink targets (record before changing)
readlink ~/.claude/commands > $BACKUP/commands.target
readlink ~/.claude/hooks > $BACKUP/hooks.target
readlink ~/.claude/agents > $BACKUP/agents.target
readlink ~/.claude/skills > $BACKUP/skills.target
readlink ~/.claude/CLAUDE.md > $BACKUP/claude-md.target
readlink ~/CLAUDE.md > $BACKUP/home-claude-md.target

# Settings + MCP
cp ~/.claude/settings.json $BACKUP/settings.json
cp ~/.claude/.mcp.json $BACKUP/mcp.json 2>/dev/null || true
cp ~/.claude/.claude.json $BACKUP/claude.json 2>/dev/null || true

# Snapshot OLD command/hook/agent/skill counts
ls ~/mekong-cli/.claude/commands/ | wc -l > $BACKUP/old-commands.count
ls ~/mekong-cli/.claude/hooks/*.cjs | wc -l > $BACKUP/old-hooks.count
ls ~/mekong-cli/.claude/agents/*.md | wc -l > $BACKUP/old-agents.count
ls ~/mekong-cli/.claude/skills/ | wc -l > $BACKUP/old-skills.count

# NEW counts
ls /Users/mac/mekong\ cli\ lastest/mekong-cli/.claude/_integration/commands/ | wc -l > $BACKUP/new-commands.count
ls /Users/mac/mekong\ cli\ lastest/mekong-cli/.claude/_pipeline/hooks/*.cjs | wc -l > $BACKUP/new-hooks.count
ls /Users/mac/mekong\ cli\ lastest/mekong-cli/.claude/_integration/agents/ | wc -l > $BACKUP/new-agents.count
ls /Users/mac/mekong\ cli\ lastest/mekong-cli/.claude/_integration/skills/ | wc -l > $BACKUP/new-skills.count

echo "Backup complete: $BACKUP"
```

## Step 1.2 — Create NEW canonical directories
The NEW repo uses layered dirs. CC CLI needs flat `commands/`, `hooks/`,
`agents/`, `skills/` at the repo root. We create **flat entry points** in the
NEW repo that point into the layered dirs, then re-point the OLD symlinks.

```bash
NEW=/Users/mac/mekong\ cli\ lastest/mekong-cli
cd $NEW

# Flat entry points → layered sources
mkdir -p .claude/commands .claude/hooks .claude/agents .claude/skills

# commands → _integration/commands
ln -sfn _integration/commands .claude/commands
# hooks → _pipeline/hooks
ln -sfn _pipeline/hooks .claude/hooks
# agents → _integration/agents
ln -sfn _integration/agents .claude/agents
# skills → _integration/skills
ln -sfn _integration/skills .claude/skills
```

## Step 1.3 — Atomically re-point OLD symlinks
```bash
# Redirect each OLD symlink to the NEW repo
ln -sfn /Users/mac/mekong\ cli\ lastest/mekong-cli/.claude/commands ~/.claude/commands
ln -sfn /Users/mac/mekong\ cli\ lastest/mekong-cli/.claude/hooks ~/.claude/hooks
ln -sfn /Users/mac/mekong\ cli\ lastest/mekong-cli/.claude/agents ~/.claude/agents
ln -sfn /Users/mac/mekong\ cli\ lastest/mekong-cli/.claude/skills ~/.claude/skills
```

## Step 1.4 — Smoke test
```bash
# Every symlink resolves
for s in commands hooks agents skills; do
  test -e ~/.claude/$s && echo "OK: $s" || echo "FAIL: $s"
done

# CC CLI can discover a known command
test -f ~/.claude/commands/plan.md && echo "OK: plan.md"
test -f ~/.claude/hooks/session-init.cjs && echo "OK: session-init.cjs"
test -f ~/.claude/agents/code-reviewer.md && echo "OK: code-reviewer.md"
test -f ~/.claude/skills/ck-plan/SKILL.md && echo "OK: ck-plan/SKILL.md"
```

## Rollback
```bash
# Restore OLD symlinks from backup
ln -sfn "$(cat ~/.claude/backups/migration-260821-2350/commands.target)" ~/.claude/commands
ln -sfn "$(cat ~/.claude/backups/migration-260821-2350/hooks.target)" ~/.claude/hooks
ln -sfn "$(cat ~/.claude/backups/migration-260821-2350/agents.target)" ~/.claude/agents
ln -sfn "$(cat ~/.claude/backups/migration-260821-2350/skills.target)" ~/.claude/skills
```

## Success Criteria
- [ ] Backup dir exists with all 4 count files + 4 target files + settings.json
- [ ] All 4 OLD symlinks resolve to NEW repo paths
- [ ] Smoke test: 4/4 symlinks OK, plan.md + session-init.cjs + code-reviewer.md + ck-plan/SKILL.md all present
- [ ] `ls ~/.claude/` shows 4 symlinks + settings.json intact

## Notes
- This phase does NOT touch settings.json, MCP, or env — those are Phase 02.
- The OLD `~/mekong-cli/.claude/` tree remains on disk as fallback until Phase 05.
- 30-day deprecation: OLD tree kept, not deleted.