# Phase 03 — Shared content (CLAUDE.md / output-styles / rules) decision

**Goal:** Resolve the 3 remaining symlinks still targeting the OLD repo.

## Current state

| Symlink | Target | NEW repo equivalent |
|---------|--------|--------------------|
| `~/.claude/CLAUDE.md` | `~/mekong-cli/GLOBAL_CONTEXT.md` | ❌ no GLOBAL_CONTEXT.md (has CLAUDE.md, AGENTS.md) |
| `~/.claude/output-styles` | OLD `.claude/output-styles` (6 files) | ❌ missing |
| `~/.claude/rules` | OLD `.claude/rules` (14 files) | ❌ missing |

⚠️ Do NOT redirect blindly — targets don't exist in NEW repo; links would break.

## Option A — Copy to NEW union layer (recommended)

1. `cp -R ~/mekong-cli/.claude/output-styles "$HOME/mekong cli lastest/mekong-cli/.claude/"`
2. `cp -R ~/mekong-cli/.claude/rules "$HOME/mekong cli lastest/mekong-cli/.claude/"`
3. Copy GLOBAL_CONTEXT.md into NEW repo root
4. Redirect the 3 symlinks (record old targets in backup dir first)
5. OLD repo stays untouched as fallback

## Option B — Keep OLD as source-of-truth for these 3

Document in execution report: "shared content intentionally served from OLD until dedup pass." No file changes.

## Acceptance (Option A)

- [ ] All 7 `~/.claude` symlinks resolve and point at NEW repo
- [ ] output-styles = 6, rules = 14 after copy

## Needs user input

Choose A or B before executing.
