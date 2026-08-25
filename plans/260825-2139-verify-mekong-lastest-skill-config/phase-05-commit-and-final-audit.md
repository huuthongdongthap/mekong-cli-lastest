# Phase 05 — Commit artifacts + final audit

**Goal:** Preserve the audit trail and produce an updated execution report.

## Steps

1. Commit untracked artifacts in NEW repo (separate commits):
   - `plans/260821-2350-mekong-config-migration/` + `plans/reports/mekong-config-migration-*.md`
   - `scripts/cutover-zunef.sh`, `scripts/validate-hooks.py`
   - this plan directory
   - Suggested: `docs(migration): commit config-migration plan, reports, validation tooling`
2. Write final audit report to `plans/reports/mekong-lastest-config-audit-260825.md`:
   - symlink table (7 links, target + resolve status)
   - counts (commands/hooks/agents/skills)
   - validate-hooks output
   - gaps closed vs deferred
3. Full smoke:
   ```bash
   ls ~/.claude/skills | wc -l          # expect 936+
   mekong --help                        # NEW banner (after phase 02)
   python3 scripts/validate-hooks.py    # all resolve
   ```

## Acceptance

- [ ] All artifacts committed; `git status --short` clean except runtime logs
- [ ] Final report exists with pass/fail per layer
- [ ] Backup dir untouched

## Rollback

Git-only; no system state changed in this phase.
