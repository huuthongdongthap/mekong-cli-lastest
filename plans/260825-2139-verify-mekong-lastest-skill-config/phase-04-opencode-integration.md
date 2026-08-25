# Phase 04 — OpenCode integration (optional)

**Goal:** Surface mekong commands/skills inside opencode, or explicitly declare out-of-scope.

## Current state

- `~/.config/opencode/skills` = real dir, 112 entries (ClaudeKit-style), only `goal-ingestion` mentions mekong
- `~/.config/opencode/command` = 75 entries, `commands` = 596 entries (legacy copies)
- NEW repo ships `.opencode/{opencode.jsonc, mcp.json, agents/}` — NOT installed
- Active `opencode.json` uses omniroute provider + mcp: cc-ai-os/stitch/pencil

## Options

### A. Sync mekong commands into opencode (low risk)
1. Copy NEW repo `.claude/commands/*.md` → `~/.config/opencode/command/mekong/` (namespaced subdir)
2. Merge `mekong-ai-os` MCP entry into active `mcpServers` config only if `src.core.mcp_server` is runnable in NEW repo venv
3. Smoke: opencode lists new commands

### B. Skip (document)
OpenCode workflow intentionally separate from Claude. Record decision in final report.

## Recommendation

Start with B unless user actively uses mekong commands from opencode — current opencode.json was hand-tuned (Aug 25) and merging risks conflicts.

## Acceptance (if A)

- [ ] Commands visible in opencode without breaking existing 75 commands
- [ ] MCP entry only added after runtime test passes
