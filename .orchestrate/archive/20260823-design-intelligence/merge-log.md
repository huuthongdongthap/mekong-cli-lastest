# Merge Log — PR #2 (Design Intelligence) — 2026-08-23

Founder authorized merge with "go". Merged without `--no-verify` and without
admin bypass.

## Result

- `gh pr merge 2 --squash --delete-branch` — **MERGED** at 2026-08-23T10:33:32Z.
  (api.github.com timed out on attempts 1–3; succeeded on attempt 4.)
- Squash commit on `main`: **0878f966fcb18781623a3cec7dab7476b7f77cf7**
  "feat(design-intelligence): Hallmark deep integration — mekong ui sub-app (#2)"

## Post-merge verification

1. Squash tree identical to branch head 9fda45a32 (`git diff --stat 9fda45a32 0878f966fc`
   → empty). No content lost or altered in the squash.
2. `src/design_intelligence/` present on origin/main: __init__, change_detect, checks,
   design_memory, dna, gates, knowledge/ (tree), pipeline, schemas, scoring, visual.
3. `dna/core-dna.json` on origin/main: version `2026.08.23`, design-intelligence registered.
4. Gate 1 CI fix on origin/main: `PYTHONPATH=src python3 -c "from seed.agents.ceo import ..."`.

## Local main sync

Local `main` had diverged (3 unpushed chore commits whose content was already inside the
branch). Reset local main to 0878f966f (`git reset --hard`) after confirming the squash
tree matched the branch head. Working tree clean afterwards.

## Post-merge smoke

- `python3 -m pytest tests/design_intelligence/ tests/cli/test_ui_commands.py -q`
  → **140 passed** in 5.14s.

## Note on ship-report.md

`.orchestrate/latest/ship-report.md` was overwritten (by another session) with the
"LLM Client Wrapping" ship report from a different task. The full Design Intelligence
ship report content is preserved in session memory and in
`~/.claude/projects/-Users-macbook/memory/20260823-design-intelligence-shipped.md`.
This merge-log.md records the final merge step for this task instead of restoring that file.

## Escrow TODOs carried to main

- T1 (MED): split 4 files >200 LOC — src/cli/ui_commands.py (261), src/cli/ui_study.py (255),
  src/design_intelligence/schemas.py (221), src/design_intelligence/checks.py (215).
- T2 (MED): reconcile Bước 9 failure-count wording (223 / 20 / 6).
- Infrastructure (repo owner): Core DNA Gate fails on any clean checkout because
  `.gitignore:59` ignores `src/cli/commands/build/` while `app_setup.py:31` imports it;
  Gate 3 pyflakes references nonexistent root `seed/`, `tools/`; smoke-tests.yml fails on main.
