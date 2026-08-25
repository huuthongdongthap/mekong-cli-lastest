# Phase 05: Validation + Rollback

## Overview
End-to-end validation of migrated config. Confirm CC CLI starts, discovers
commands, runs hooks, loads agents/skills. Prepare rollback if needed.

## Priority
P0 — blocking. Must pass before declaring migration complete.

## Status
pending

## Validation Matrix

| Check | Command | Pass Criteria |
|-------|---------|---------------|
| Settings JSON valid | `python3 -m json.tool ~/.claude/settings.json` | No parse error |
| Model routing present | `jq '.modelRouting.rules | length' ~/.claude/settings.json` | >= 15 |
| Hooks present | `jq '.hooks | keys' ~/.claude/settings.json` | 8 events |
| Symlinks resolve | `for s in commands hooks agents skills; do test -e ~/.claude/\$s; done` | 4/4 OK |
| Commands discoverable | `ls ~/.claude/commands/*.md | wc -l` | >= 466 (OLD preserved + NEW merged) |
| Core commands present | `test -f ~/.claude/commands/plan.md` etc | 6/6 OK |
| Hooks resolve to files | `python3 validate-hooks.py` | 0 missing |
| Core hooks present | `test -f ~/.claude/hooks/session-init.cjs` etc | 5/5 OK |
| Agents discoverable | `ls ~/.claude/agents/*.md | wc -l` | >= 20 |
| Core agents present | `test -f ~/.claude/agents/cto.md` etc | 7/7 OK |
| Skills discoverable | `ls ~/.claude/skills/*/SKILL.md | wc -l` | >= 34 |
| Core skills present | `test -f ~/.claude/skills/ck-plan/SKILL.md` etc | 5/5 OK |
| MCP config present | `test -f ~/.claude/.mcp.json` | OK |
| Auth token preserved | `jq '.env.ANTHROPIC_AUTH_TOKEN' ~/.claude/settings.json` | non-empty |
| CC CLI starts | `timeout 5 claude --version` | exits 0 |
| Command dispatch works | `python3 -m src.main plan --help` (from NEW repo) | exits 0 |

## Step 5.1 — Run validation suite
```bash
NEW=/Users/mac/mekong\ cli\ lastest/mekong-cli

# 1. Settings
python3 -m json.tool ~/.claude/settings.json > /dev/null && echo "settings: OK"

# 2. Model routing
python3 -c "
import json
d=json.load(open('/Users/mac/.claude/settings.json'))
print('modelRouting rules:', len(d.get('modelRouting',{}).get('rules',[])))
print('modelRouting providers:', list(d.get('modelRouting',{}).get('providers',{}).keys()))
"

# 3. Symlinks
for s in commands hooks agents skills; do
  test -e ~/.claude/\$s && echo "symlink \$s: OK" || echo "symlink \$s: FAIL"
done

# 4. Commands
for cmd in plan cook fix scout code-review ship test; do
  test -f ~/.claude/commands/\$cmd.md && echo "cmd \$cmd: OK" || echo "cmd \$cmd: FAIL"
done

# 5. Hooks
python3 $NEW/scripts/validate-hooks.py

# 6. Agents
for agent in cto cfo cmo coo cso debugger tester; do
  test -f ~/.claude/agents/\$agent.md && echo "agent \$agent: OK" || echo "agent \$agent: FAIL"
done

# 7. Skills
for skill in ck-plan cook fix scout research; do
  test -f ~/.claude/skills/\$skill/SKILL.md && echo "skill \$skill: OK" || echo "skill \$skill: FAIL"
done

# 8. MCP
test -f ~/.claude/.mcp.json && echo "mcp.json: OK" || echo "mcp.json: MISSING"

# 9. Auth token
python3 -c "
import json
t=json.load(open('/Users/mac/.claude/settings.json')).get('env',{}).get('ANTHROPIC_AUTH_TOKEN','')
print('auth token:', 'PRESENT' if t else 'MISSING')
"

# 10. CC CLI start
timeout 5 claude --version 2>&1 | head -1

# 11. Mekong CLI dispatch
cd $NEW && python3 -m src.main plan --help 2>&1 | head -3
```

## Step 5.2 — Hook validation script
```bash
cat > /Users/mac/mekong\ cli\ lastest/mekong-cli/scripts/validate-hooks.py <<'PY'
#!/usr/bin/env python3
import json, os, sys

settings = json.load(open(os.path.expanduser('~/.claude/settings.json')))
missing = []

for ev, lst in settings.get('hooks', {}).items():
    for entry in lst:
        for h in entry.get('hooks', []):
            cmd = h.get('command', '')
            # Extract file path from 'node <path>'
            for part in cmd.split():
                if part.endswith('.cjs'):
                    # Expand $CLAUDE_PROJECT_DIR
                    path = part.replace('$CLAUDE_PROJECT_DIR', '/Users/mac/mekong cli lastest/mekong-cli')
                    if not os.path.exists(path):
                        missing.append((ev, path))

if missing:
    print('MISSING HOOK FILES:', file=sys.stderr)
    for ev, p in missing:
        print(f'  [{ev}] {p}', file=sys.stderr)
    sys.exit(1)
else:
    print('All hook files resolve')
    sys.exit(0)
PY
chmod +x /Users/mac/mekong\ cli\ lastest/mekong-cli/scripts/validate-hooks.py
```

## Step 5.3 — Smoke test mekong commands
```bash
NEW=/Users/mac/mekong\ cli\ lastest/mekong-cli
cd $NEW

# Test core commands
python3 -m src.main --help 2>&1 | head -5
python3 -m src.main plan --help 2>&1 | head -3
python3 -m src.main cook --help 2>&1 | head -3
python3 -m src.main fix --help 2>&1 | head -3

# Verify wrapper script works
source scripts/shell-init.sh
mekong --help 2>&1 | head -3
```

## Rollback Procedures

### Full Rollback (all phases)
```bash
BACKUP=~/.claude/backups/migration-260821-2350

# 1. Restore settings
cp $BACKUP/settings.json ~/.claude/settings.json

# 2. Restore symlinks
ln -sfn "$(cat $BACKUP/commands.target)" ~/.claude/commands
ln -sfn "$(cat $BACKUP/hooks.target)" ~/.claude/hooks
ln -sfn "$(cat $BACKUP/agents.target)" ~/.claude/agents
ln -sfn "$(cat $BACKUP/skills.target)" ~/.claude/skills
ln -sfn "$(cat $BACKUP/claude-md.target)" ~/.claude/CLAUDE.md
ln -sfn "$(cat $BACKUP/home-claude-md.target)" ~/CLAUDE.md

# 3. Restore MCP
cp $BACKUP/mcp.json ~/.claude/.mcp.json 2>/dev/null || true

# 4. Restore OLD content
rsync -a --delete ~/mekong-cli/.claude/commands-backup/ ~/mekong-cli/.claude/commands/
rsync -a --delete ~/mekong-cli/.claude/skills-backup/ ~/mekong-cli/.claude/skills/
rsync -a --delete ~/mekong-cli/.claude/agents-backup/ ~/mekong-cli/.claude/agents/

echo "Full rollback complete"
```

### Phase-specific Rollback
| Phase | Rollback |
|-------|----------|
| 01 | Restore 4 symlinks from backup targets |
| 02 | `cp $BACKUP/settings.json ~/.claude/settings.json` |
| 03 | Restore deprecated hooks, revert settings hook paths |
| 04 | Restore content from `*-backup/` dirs |

## Success Criteria
- [ ] All 11 validation checks pass
- [ ] 0 missing hook files
- [ ] CC CLI starts in < 5s
- [ ] Mekong CLI dispatches core commands
- [ ] Rollback script tested and ready

## Notes
- If any validation fails, run the corresponding phase rollback, fix, re-run.
- Keep backup dir for 30 days (deprecation window).
- Document any manual adjustments needed post-migration.