# Mekong Config Migration — Execution Report

Date: 2026-08-24 | Plan: `plans/260821-2350-mekong-config-migration/` | Mode: --auto

## Result: ✅ 25/25 validation checks passed

## What was executed

### Phase 01 — Backup + Symlink Redirect
- Backup: `~/.claude/backups/migration-260821-2350/` (settings.json, mcp.json, 5 symlink targets, old/new counts)
- Built **union layer** in NEW repo `.claude/`: OLD content first, NEW canonical overlaid on top (shared names → NEW wins)
  - commands: 464 OLD + 119 NEW = **491** (92 shared → NEW version)
  - hooks: 26 NEW + auto-compact-monitor (OLD-only) = **27**
  - agents: 14 OLD + 20 NEW = **28** (6 shared → NEW)
  - skills: 885 OLD + 34 NEW = **893** (29 shared → NEW)
- Redirected 4 symlinks: `~/.claude/{commands,hooks,agents,skills}` → `/Users/mac/mekong cli lastest/mekong-cli/.claude/*`
- Supporting pieces copied: workflows/, schemas/, scripts/, settings.local.json, statusline.sh/.cjs

### Phase 02 — Settings Merge (Stage A applied)
Merged per decision matrix into `~/.claude/settings.json`:
- **env**: NEW base (zunef cloud URL) + 9 battle-tested OLD tuning keys; dropped 8 pmv-gateway-specific keys + literal token
- **modelRouting**: NEW wholesale (13 rules, zunef+ollama) + added `pmv-gateway` provider (localhost:20128, priority 90) as fallback
- **hooks**: NEW wiring (7 events, 15 hook invocations); removed broken brainstorm-vn-inject ref; wired stop-checkpoint.cjs into Stop
- **permissions**: allow=union(35), deny=NEW(.env+rm-rf guards), ask=NEW
- **mcp**: union 7 servers (NEW filesystem/git/sqlite/memory + OLD stitch kit)
- **model**: pmv-balance → claude-fable-5; added fastMode:true
- Runtime-state keys kept from OLD (theme/effort/ultracode/autoMemory*/onboarding)

### Phase 03 — Hooks Validation (+ bug fixes found during execution)
Bugs discovered & fixed beyond plan:
1. **4 broken symlinks** in NEW repo pointing to `/Users/macbook/` (upstream author's machine): `user-prompt-routing.cjs` ×2, `__tests__` ×2 — replaced with real files
2. **6 missing lib modules** required by hooks (`context-builder`, `model-router`, `model-router-config`, `flash-failure-store`, `usage-cost-tracker`) — restored from `_archive/mekong/mekong/hooks/lib/`
3. **Alias gap**: hooks require `./lib/mk:config-utils.cjs` and `./lib/ck:config-utils.cjs` but upstream only ships `ck-config-utils.cjs` — created both alias copies

Verification:
- `scripts/validate-hooks.py` (new): 15/15 wired hooks resolve
- Local requires: all resolve (89 checked, comment false-positive excluded)
- Syntax: 27/27 hooks pass `node --check`
- Runtime smoke: session-init / dev-rules-reminder / pre-tool-use-guard execute rc=0 with real output

## Final state

| Layer | Path | Content |
|-------|------|---------|
| Source of truth | `mekong cli lastest/mekong-cli/.claude/` | union layer (491 cmds / 27 hooks / 28 agents / 893 skills) |
| Active config | `~/.claude/` | 4 symlinks → source of truth + merged settings.json |
| Rollback | `~/.claude/backups/migration-260821-2350/` | full pre-migration state |
| OLD system | `~/mekong-cli/` | untouched, intact as 30-day fallback |

## Stage B (pending user action): Zunef token cutover

Current env points to `https://claude-api.zunef.com/v1/ai` but auth token not yet provisioned for cloud direct. When ready:

```bash
# 1. Store token in Keychain (one time)
security add-generic-password -s mekong-zunef -a $USER -w <ZUNEF_TOKEN>

# 2. Run cutover script
"/Users/mac/mekong cli lastest/mekong-cli/scripts/cutover-zunef.sh"
```

Until Stage B runs, if zunef cloud rejects requests, rollback to working gateway:
```bash
# edit ~/.claude/settings.json → env.ANTHROPIC_BASE_URL = "http://localhost:20128"
```

## Rollback (full, if ever needed)
```bash
BK=~/.claude/backups/migration-260821-2350
cp $BK/settings.json ~/.claude/settings.json
ln -sfn "$(cat $BK/commands.target)" ~/.claude/commands
ln -sfn "$(cat $BK/hooks.target)" ~/.claude/hooks
ln -sfn "$(cat $BK/agents.target)" ~/.claude/agents
ln -sfn "$(cat $BK/skills.target)" ~/.claude/skills
```

## Unresolved questions
1. Zunef token chưa cấp — Stage B chờ. Model IDs (`claude-fable-5`, `claude-opus-4-6[1m]`...) chưa verify với cloud endpoint.
2. `settings-zunef.json` (dùng bởi wrapper `claude-zunef`) vẫn trỏ localhost:20128 — có cần sync sang zunef cloud luôn không?
3. CC CLI restart cần thiết để nạp settings mới — nên restart session hiện tại sau khi xác nhận zunef token.


## Stage B COMPLETED (2026-08-24 10:30)

### Zunef cloud verification results
| Model | Status |
|-------|--------|
| claude-fable-5 | ✅ OK |
| claude-sonnet-5-0 | ✅ OK |
| claude-opus-4-6 / 4-7 / 4-8 | ✅ OK |
| claude-haiku-4-5 | ✅ OK |
| `*[1m]` suffix | ❌ NOT supported → replaced with base model + betaHeaders note |

Both hostnames work: `claude-api.zunef.com` and `claude.zunef.com`. Kept `claude-api.zunef.com`.

### Changes applied
1. Token → macOS Keychain (`mekong-zunef`), helper script `~/.claude/scripts/get-zunef-token.sh` (chmod 600/755)
2. 3 routing rules fixed: `[1m]` suffix removed, beta header noted
3. `env.ANTHROPIC_BASE_URL` = `https://claude-api.zunef.com/v1/ai` (live)
4. No literal token anywhere in config files

### Fallback ladder (final)
zunef cloud → pmv-gateway localhost:20128 (priority 90) → ollama qwen3:35b-cc (priority 99)

**Migration fully complete. Restart CC CLI session to load new settings.**
