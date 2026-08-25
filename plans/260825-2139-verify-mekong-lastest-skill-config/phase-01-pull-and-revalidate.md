# Phase 01 — Pull latest + revalidate hooks

**Goal:** Make "latest" true and confirm the union layer still passes validation after upstream changes.

## Steps

1. Check working tree is safe to pull (only runtime-state modifications expected: `_pipeline/hooks/.logs/`, `__tests__`, `user-prompt-routing.cjs` type-change)
   ```bash
   git -C "/Users/mac/mekong cli lastest/mekong-cli" stash push -m "runtime-state pre-pull" -- .claude/_pipeline/
   git -C "/Users/mac/mekong cli lastest/mekong-cli" pull origin main
   git -C "/Users/mac/mekong cli lastest/mekong-cli" stash pop
   ```
2. Re-run hook validation
   ```bash
   python3 "/Users/mac/mekong cli lastest/mekong-cli/scripts/validate-hooks.py"
   ```
3. Syntax-check all hooks
   ```bash
   find ~/.claude/hooks -name "*.cjs" -exec node --check {} \;
   ```
4. Runtime smoke: session-init / pre-tool-use-guard execute rc=0

## Acceptance

- [ ] `git rev-list HEAD..origin/main --count` = 0
- [ ] validate-hooks.py reports all wired hooks resolve
- [ ] 0 syntax errors across hooks

## Rollback

`git reset --hard <pre-pull-sha>` (record SHA before step 1).
