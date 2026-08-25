# Phase 03: Hooks Migration

## Overview
Migrate hooks from OLD flat `~/mekong-cli/.claude/hooks/` (23 hooks) to NEW
layered `.claude/_pipeline/hooks/` (26 hooks). Preserve unique OLD hooks,
adopt NEW hooks, archive deprecated ones.

## Priority
P1 — high. Hooks gate every tool call.

## Status
pending

## Hook Delta Map

| Hook | OLD | NEW _pipeline | mekong/hooks | Action |
|------|-----|---------------|--------------|--------|
| cook-after-plan-reminder.cjs | ✓ | ✓ | ✓ | adopt NEW |
| descriptive-name.cjs | ✓ | ✓ | ✓ | adopt NEW |
| dev-rules-reminder.cjs | ✓ | ✓ | ✓ | adopt NEW |
| plan-format-kanban.cjs | ✓ | ✓ | ✓ | adopt NEW |
| post-edit-simplify-reminder.cjs | ✓ | ✓ | — | adopt NEW |
| pre-compact-state-saver.cjs | ✓ | ✓ | — | adopt NEW |
| pre-tool-use-guard.cjs | ✓ | ✓ | — | adopt NEW |
| privacy-block.cjs | ✓ | ✓ | ✓ | adopt NEW |
| scout-block.cjs | ✓ | ✓ | ✓ | adopt NEW |
| session-end-telemetry.cjs | ✓ | ✓ | — | adopt NEW |
| session-init.cjs | ✓ | ✓ | ✓ | adopt NEW |
| session-state.cjs | ✓ | ✓ | ✓ | adopt NEW |
| simplify-gate.cjs | ✓ | ✓ | ✓ | adopt NEW |
| skill-dedup.cjs | ✓ | ✓ | — | adopt NEW |
| stop-checkpoint.cjs | ✓ | ✓ | — | adopt NEW |
| subagent-init.cjs | ✓ | ✓ | ✓ | adopt NEW |
| task-completed-handler.cjs | ✓ | ✓ | — | adopt NEW |
| team-context-inject.cjs | ✓ | ✓ | ✓ | adopt NEW |
| teammate-idle-handler.cjs | ✓ | ✓ | — | adopt NEW |
| usage-context-awareness.cjs | ✓ | ✓ | ✓ | adopt NEW |
| usage-quota-cache-refresh.cjs | ✓ | ✓ | ✓ | adopt NEW |
| workflow-artifact-gate.cjs | ✓ | ✓ | ✓ | adopt NEW |
| **auto-compact-monitor.cjs** | ✓ | — | — | **DEPRECATED** — superseded by pre-compact-state-saver |
| **harness-orchestrator.cjs** | — | ✓ | — | **NEW** — adopt |
| **pr-auto-merge-context.cjs** | — | ✓ | — | **NEW** — adopt |
| **user-prompt-routing.cjs** | — | ✓ | ✓ | **NEW** — adopt |
| **zunef-model-purge.cjs** | — | ✓ | — | **NEW** — adopt |
| **boundary-check.cjs** | — | — | ✓ | **ARCHIVE** — mekong-only, not in settings |
| **kv-cache-metrics.cjs** | — | — | ✓ | **ARCHIVE** — mekong-only |
| **military-law-inject.cjs** | — | — | ✓ | **ARCHIVE** — mekong-only |
| **zunef-jwt-reminder.cjs** | — | — | ✓ | **ARCHIVE** — mekong-only |

## Step 3.1 — Verify NEW hooks are self-contained
```bash
NEW=/Users/mac/mekong\ cli\ lastest/mekong-cli
for h in .claude/_pipeline/hooks/*.cjs; do
  test -f "$NEW/$h" && echo "OK: $h" || echo "FAIL: $h"
done
# Expected: 26 OK
```

## Step 3.2 — Verify NEW hook lib dependencies
```bash
NEW=/Users/mac/mekong\ cli\ lastest/mekong-cli
# Every NEW hook must resolve its requires
cd $NEW/.claude/_pipeline/hooks
node -e "
const fs=require('fs');
const files=fs.readdirSync('.').filter(f=>f.endsWith('.cjs'));
const deps=new Set();
files.forEach(f=>{
  const c=fs.readFileSync(f,'utf8');
  (c.match(/require\(['\"]([^'\"]+)['\"]\)/g)||[]).forEach(m=>{
    const d=m.match(/require\(['\"]([^'\"]+)['\"]\)/)[1];
    if(d.startsWith('.')) deps.add(d);
  });
});
console.log('local deps:', [...deps].sort().join(', '));
"
```

## Step 3.3 — Update settings.json hook paths
The NEW settings already uses `$CLAUDE_PROJECT_DIR/.claude/_pipeline/hooks/...`
paths. After Phase 01 symlink redirect, `$CLAUDE_PROJECT_DIR/.claude/hooks`
→ `_pipeline/hooks`. Verify:

```bash
python3 -c "
import json
d=json.load(open('/Users/mac/.claude/settings.json'))
for ev,lst in d.get('hooks',{}).items():
    for entry in lst:
        for h in entry.get('hooks',[]):
            cmd=h.get('command','')
            if '_pipeline/hooks' in cmd:
                print('OK:', cmd)
            else:
                print('CHECK:', cmd)
"
```

## Step 3.4 — Archive deprecated hooks
```bash
mkdir -p ~/.claude/backups/migration-260821-2350/hooks/deprecated
# Move deprecated hooks out of active path
mv ~/mekong-cli/.claude/hooks/auto-compact-monitor.cjs \
   ~/.claude/backups/migration-260821-2350/hooks/deprecated/ 2>/dev/null || true
```

## Step 3.5 — Smoke test
```bash
# Every hook in settings.json resolves to a real file
python3 -c "
import json, os
d=json.load(open('/Users/mac/.claude/settings.json'))
missing=[]
for ev,lst in d.get('hooks',{}).items():
    for entry in lst:
        for h in entry.get('hooks',[]):
            cmd=h.get('command','')
            # Extract path from 'node <path>'
            parts=cmd.split()
            for p in parts:
                if p.endswith('.cjs'):
                    p=p.replace('\$CLAUDE_PROJECT_DIR','/Users/mac/mekong cli lastest/mekong-cli')
                    if not os.path.exists(p):
                        missing.append(p)
if missing:
    print('MISSING:', missing)
else:
    print('all hooks resolve')
"
```

## Rollback
```bash
# Restore OLD hooks from backup
cp ~/.claude/backups/migration-260821-2350/hooks/deprecated/*.cjs ~/mekong-cli/.claude/hooks/ 2>/dev/null || true
```

## Success Criteria
- [ ] All 26 NEW hooks exist and are executable
- [ ] All hook lib deps resolve locally
- [ ] Every hook path in settings.json resolves to a real file
- [ ] Deprecated hooks archived (not deleted)
- [ ] Smoke test: 0 missing hooks

## Notes
- `boundary-check.cjs`, `kv-cache-metrics.cjs`, `military-law-inject.cjs`,
  `zunef-jwt-reminder.cjs` live only in `mekong/hooks/` (engine layer) —
  they are NOT in settings.json, so no action needed beyond archiving.
- `harness-orchestrator.cjs` is NEW and not yet wired into settings.json —
  add it in a follow-up if the orchestrator feature is enabled.