# Phase 02 — mekong bin wrapper cutover

**Goal:** `/Users/mac/bin/mekong` dispatches through the NEW repo wrapper.

## Current state

```bash
# /Users/mac/bin/mekong (3 lines)
export MEKONG_ROOT="/Users/mac/mekong-cli"          # ← OLD
exec bash "$MEKONG_ROOT/scripts/mekong-wrapper.sh" "$@"
```

## Change

Point `MEKONG_ROOT` to the NEW repo (path contains a space — quote it):

```bash
#!/usr/bin/env bash
export MEKONG_ROOT="$HOME/mekong cli lastest/mekong-cli"
exec bash "$MEKONG_ROOT/scripts/mekong-wrapper.sh" "$@"
```

## Pre-flight

1. Diff old vs new wrapper: `diff /Users/mac/mekong-cli/scripts/mekong-wrapper.sh "$HOME/mekong cli lastest/mekong-cli/scripts/mekong-wrapper.sh"`
2. Confirm new wrapper's dept-install path exists: `$MEKONG_ROOT/clipmart/departments/` — NOTE: OLD repo audit showed no `clipmart/` dir; verify NEW has it or the install subcommand degrades gracefully
3. Backup: `cp /Users/mac/bin/mekong ~/.claude/backups/migration-260821-2350/mekong.bin.bak`
4. Smoke test after change:
   ```bash
   mekong --help
   mekong install            # should list departments (not error)
   ```

## Fallback

Keep OLD one-shot available:
```bash
alias mekong-old='MEKONG_ROOT=/Users/mac/mekong-cli bash /Users/mac/mekong-cli/scripts/mekong-wrapper.sh'
```

## Acceptance

- [ ] `mekong --help` prints NEW wrapper banner
- [ ] `bash -n /Users/mac/bin/mekong` passes

## Rollback

Restore backup file.
