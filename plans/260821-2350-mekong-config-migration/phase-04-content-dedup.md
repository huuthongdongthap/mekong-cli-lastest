# Phase 04: Content Dedup (Commands / Skills / Agents)

## Overview
Map OLD → NEW for commands, skills, agents. Preserve OLD domain-specific
content, adopt NEW canonical versions, archive unmapped.

## Priority
P1 — high. Missing commands = broken user workflows.

## Status
pending

## Delta Summary (verified 2026-08-21)

| Content | OLD | NEW | Shared | OLD-only | NEW-only |
|---------|-----|-----|--------|----------|----------|
| Commands | 466 | 119 | 92 | 374 | 27 |
| Skills | 896 | 34 | 29 | 867 | 5 (+3 meta) |
| Agents | 14 | 20 | 6 | 8 | 14 |

### Shared skills (29)
ai-artist, ai-multimodal, ask, chrome-profile, coding-level, context-engineering,
cook, cti-expert, design, docs-seeker, fix, markdown-novel-viewer, plans-kanban,
preview, research, scout, sequential-thinking, show-off, skill-creator, stitch,
team, tech-graph, threejs, use-mcp, watzup, worktree (+ install.ps1, install.sh meta)

### NEW-only skills (5)
ck-graphify, ck-plan, ck-scenario, document-skills, excalidraw
(+ README.md, _shared/, agent_skills_spec.md meta files)

### Shared agents (6)
code-reviewer, docs-manager, fullstack-developer, planner, researcher, ui-ux-designer

### OLD-only agents (8)
agentic-overlord, capital-allocator, content-agent, docs-writer-agent,
file-scout-agent, git-ops-agent, shell-runner-agent, stitch-kit

### NEW-only agents (14)
brainstormer, cfo, cmo, code-simplifier, coo, cso, cto, debugger,
git-manager, journal-writer, kongming, project-manager, sun-tzu, tester

## Critical Finding: Skills
OLD has **896 skills** (domain-specific: accounting-agent, agri-tech,
adversarial-review, etc.). NEW has only **34 core skills**.

**Decision: KEEP OLD skills.** The NEW repo's 34 skills are the canonical
core; the OLD 896 are the working domain set. We merge by:
1. Adopt NEW canonical versions where they exist (same name → NEW wins)
2. Keep OLD-only skills (they're the working set)
3. Archive NEW-only skills that duplicate OLD behavior

## Step 4.1 — Commands: adopt NEW, preserve OLD-only
```bash
NEW=/Users/mac/mekong\ cli\ lastest/mekong-cli
OLD=~/mekong-cli

# Shared commands (92): NEW canonical wins
comm -12 <(ls $OLD/.claude/commands/*.md | xargs -n1 basename | sed 's/.md//' | sort) \
         <(ls $NEW/.claude/_integration/commands/*.md | xargs -n1 basename | sed 's/.md//' | sort) \
  > /tmp/shared-cmds.txt

# OLD-only commands (374): keep as-is, log to archive manifest
comm -23 <(ls $OLD/.claude/commands/*.md | xargs -n1 basename | sed 's/.md//' | sort) \
         <(ls $NEW/.claude/_integration/commands/*.md | xargs -n1 basename | sed 's/.md//' | sort) \
  > /tmp/old-only-cmds.txt

# NEW-only commands (27): adopt
comm -13 <(ls $OLD/.claude/commands/*.md | xargs -n1 basename | sed 's/.md//' | sort) \
         <(ls $NEW/.claude/_integration/commands/*.md | xargs -n1 basename | sed 's/.md//' | sort) \
  > /tmp/new-only-cmds.txt

echo "Shared: $(wc -l < /tmp/shared-cmds.txt)"
echo "OLD-only: $(wc -l < /tmp/old-only-cmds.txt)"
echo "NEW-only: $(wc -l < /tmp/new-only-cmds.txt)"
```

## Step 4.2 — Skills: merge NEW core + OLD domain
```bash
NEW=/Users/mac/mekong\ cli\ lastest/mekong-cli
OLD=~/mekong-cli

# NEW skills (34) — canonical core
cp -r $NEW/.claude/_integration/skills/* $OLD/.claude/skills/ 2>/dev/null || true

# Verify no overwrite of unique OLD skills
# (cp -n would skip; use rsync --ignore-existing to be safe)
rsync -a --ignore-existing $NEW/.claude/_integration/skills/ $OLD/.claude/skills/
```

## Step 4.3 — Agents: adopt NEW C-suite, preserve OLD specialists
```bash
NEW=/Users/mac/mekong\ cli\ lastest/mekong-cli
OLD=~/mekong-cli

# Shared agents (6): NEW canonical wins
# code-reviewer, docs-manager, fullstack-developer, planner, researcher, ui-ux-designer

# NEW-only agents (14) to adopt:
# brainstormer, cfo, cmo, code-simplifier, coo, cso, cto, debugger,
# git-manager, journal-writer, kongming, project-manager, sun-tzu, tester

# OLD-only agents (8) to preserve:
# agentic-overlord, capital-allocator, content-agent, docs-writer-agent,
# file-scout-agent, git-ops-agent, shell-runner-agent, stitch-kit

# Merge: rsync NEW agents over OLD, preserving OLD-only
rsync -a --ignore-existing $NEW/.claude/_integration/agents/ $OLD/.claude/agents/
```

## Step 4.4 — Archive manifest
```bash
cat > /tmp/archive-manifest.json <<EOF
{
  "migration": "260821-2350-mekong-config-migration",
  "commands": {
    "shared": $(wc -l < /tmp/shared-cmds.txt),
    "old_only_preserved": $(wc -l < /tmp/old-only-cmds.txt),
    "new_only_adopted": $(wc -l < /tmp/new-only-cmds.txt)
  },
  "skills": {
    "new_canonical": 34,
    "old_domain_preserved": 885
  },
  "agents": {
    "new_adopted": 14,
    "old_preserved": 8
  }
}
EOF
```

## Step 4.5 — Smoke test
```bash
# Every NEW canonical command exists
for cmd in plan cook fix scout code-review ship test; do
  test -f ~/.claude/commands/$cmd.md && echo "OK: $cmd" || echo "FAIL: $cmd"
done

# Every NEW canonical skill exists
for skill in ck-plan cook fix scout research; do
  test -f ~/.claude/skills/$skill/SKILL.md && echo "OK: $skill" || echo "FAIL: $skill"
done

# Every NEW canonical agent exists
for agent in cto cfo cmo coo cso debugger tester planner code-reviewer; do
  test -f ~/.claude/agents/$agent.md && echo "OK: $agent" || echo "FAIL: $agent"
done

# Every OLD-only preserved agent exists
for agent in agentic-overlord capital-allocator stitch-kit file-scout-agent; do
  test -f ~/.claude/agents/$agent.md && echo "OK: $agent" || echo "FAIL: $agent"
done
```

## Rollback
```bash
# Restore OLD content from backup
rsync -a --delete ~/mekong-cli/.claude/commands-backup/ ~/mekong-cli/.claude/commands/
rsync -a --delete ~/mekong-cli/.claude/skills-backup/ ~/mekong-cli/.claude/skills/
rsync -a --delete ~/mekong-cli/.claude/agents-backup/ ~/mekong-cli/.claude/agents/
```

## Success Criteria
- [ ] All 92 shared commands resolve to NEW canonical version
- [ ] All 374 OLD-only commands preserved
- [ ] All 27 NEW-only commands adopted
- [ ] 896 OLD skills preserved + 34 NEW skills merged (29 shared, 5 NEW-only)
- [ ] 20 NEW agents present + 8 OLD-only agents preserved (6 shared)
- [ ] Smoke test: 6/6 commands, 5/5 skills, 12/12 agents OK

## Notes
- 30-day deprecation: OLD-only commands/skills/agents kept, not deleted.
- NEW-only commands (27) are the canonical set — these replace OLD equivalents
  where names differ (e.g. OLD `cto-dashboard` → NEW `cto` agent + `mk-status` cmd).
- Skills merge uses `rsync --ignore-existing` to avoid clobbering unique OLD skills.