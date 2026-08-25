# So sánh kiến trúc & giao tiếp: Mekong CLI OLD vs NEW

Date: 2026-08-24 | Scope: ~/mekong-cli (OLD) vs "mekong cli lastest/mekong-cli" (NEW)

---

## 1. Kiến trúc tổng thể

| Khía cạnh | OLD | NEW |
|-----------|-----|-----|
| Triết lý | Flat monolith — mọi thứ nằm phẳng trong `.claude/` | Layered by purpose — `_core/_pipeline/_integration/_quality/_archive` |
| Engine | `src/core/` phẳng ~193 files, `orchestrator.py`, `pev_*` rải rác | `src/harness/` cấu trúc: `pev/` (22 modules), `agents/`, `core/`, `observability/`, `evals/`, `sops-engine/` (51 files) |
| DI | Không có — import trực tiếp | `di_container.py` (services/controllers registry) |
| Governance zones | Không phân vùng | Quân Doanh (config fortified, cần `/binh-phap win`) vs Doanh Trại (free-edit) |
| Template mgmt | Thủ công | `.ck.json` + metadata.json versioned deletions manifest |

### OLD layout
```
~/mekong-cli/.claude/
├── commands/   477 .md (flat, prompt-inline)
├── hooks/      23 .cjs (flat)
├── skills/     896 dirs
├── agents/     14 .md
├── workflows/  10 .md
├── schemas/    2 json
├── settings.json (+settings.local.json), mcp.json, statusline.sh
~/.claude/ ← symlink từng mục vào ~/mekong-cli/.claude/
```

### NEW layout
```
mekong-cli/.claude/
├── _core/         settings.json, agent-registry.json, metadata.json,
│                  statusline.cjs, .ck.json, .env.example, agent-memory/
├── _pipeline/     hooks/ (26 .cjs + lib/ 20 modules + tests), scripts/, command-archive/
├── _integration/  commands/ (119), agents/ (20), skills/ (34)
├── _quality/      rules/ (9), schemas/, cheatsheets/
└── _archive/      legacy mekong/ hooks + bootstrap (đóng băng)
```

## 2. Kiến trúc giao tiếp (communication)

### OLD — Subprocess spawn + inline-prompt
```
User ──► ~/.claude/commands/X.md  (prompt đầy đủ inline, LLM tự diễn giải)
              │
              ▼
        scripts/mekong-wrapper.sh ──spawn──► claude binary
              │                              (KHÔNG kế thừa harness:
              ▼                               không hooks/skills/memory)
        mekong/adapters/cc-cli.sh ...
```
- **Lỗ hổng đã ghi nhận chính thức** (`DESIGN_DUAL_CLI.md`): "`mk` just spawns `claude` binary via wrapper → inherits NO Mekong harness".
- Dual-brain qua 2 configs tách biệt: CTO (Qwen 3.6 35B local, `~/.claude-developer/settings-cto.json`) ↔ Worker (Claude Code CLI) — giao tiếp bằng cách chạy 2 CLI riêng.
- Paths **hardcode tuyệt đối**: `node /Users/mac/mekong-cli/.claude/hooks/session-init.cjs`.
- CLAUDE.md = GLOBAL_CONTEXT.md mega-loader (KV-cache prefix, toàn bộ catalog 505 commands nhét vào context).
- Hooks độc lập, ít chia sẻ code (chỉ `lib/` nhỏ).

### NEW — Single-host harness + thin-dispatch
```
User ──► .claude/_integration/commands/X.md  (THIN dispatcher)
              │
              │    ```bash
              │    mekong fix $ARGUMENTS     ← 99/119 commands chạy kiểu này
              │    ```
              ▼
        Harness Host (Python Typer, src/main.py)
        ├── Hook Engine (_pipeline/hooks + lib/ chung:
        │     ck-config-utils, hook-logger, session-state-manager)
        ├── modelRouting: match tên command → provider/model
        ├── Command Fabric: catalog → sinh adapters cho
        │     vim/emacs/helix/zed/neovim/sublime/JetBrains/MCP/shell
        ├── MCP server riêng: src/core/mcp_server.py (mekong-ai-os)
        └── PEV loop: Plan→Execute→Verify (dag_scheduler, checkpoint,
              retry_policy, verifier...)
```
- Paths **relative**: `$CLAUDE_PROJECT_DIR/.claude/_pipeline/hooks/...` — portable.
- Provider abstraction trong settings: `modelRouting.providers` = zunef (cloud) + ollama (local, priority 99 fallback).
- Hooks dùng chung `lib/` (20 modules có unit tests) → state nhất quán giữa session-init/statusline/session-state.
- Statusline `.cjs` đọc cùng session-state cache với hooks → UI đồng bộ state.

## 3. Model routing

| | OLD | NEW |
|---|-----|-----|
| Cơ chế | `modelRouter`: {default, architect, escalationThreshold 0.6, maxProPercentage 15} | `modelRouting.rules[]`: 15 rules match theo TÊN COMMAND (mk-plan→sonnet-5, mk-deep→opus[1m], mk-crawl→haiku...) |
| Định tuyến | Theo vai trò (flash/pro %) | Theo loại công việc (plan/debug/review/crawl/orchestrate) |
| Providers | Implicit (env ANTHROPIC_*) | Explicit: zunef + ollama với baseUrl/timeout/priority |

## 4. Command surface

| | OLD | NEW |
|---|-----|-----|
| Số lượng | 477 (466 top-level .md) | 119 (+subdirs = 159 .md) |
| Bản chất | Prompt-inline: toàn bộ logic nằm trong .md, LLM đọc rồi thực hiện | Thin-dispatch: frontmatter + 1 lệnh `mekong <cmd>`, logic nằm trong Python engine |
| Nguồn chân lý | Copy-paste giữa .claude và .opencode (870 bản OpenCode wrap bằng template text) | `src/command_fabric/catalog.py` — 1 catalog sinh adapters cho mọi IDE/CLI |
| Namespacing | Flat + subdir | Layer: `_integration` (định nghĩa) ≠ `_pipeline/command-archive` (lưu trữ) |

## 5. Agents & Skills

| | OLD | NEW |
|---|-----|-----|
| Agents | 14 (specialists: agentic-overlord, stitch-kit...) | 20 (C-suite: cto/cfo/cmo/coo/cso + kongming, sun-tzu) + `agent-registry.json` khai báo model/tools |
| Skills | 896 (domain khổng lồ) | 34 core canonical + `_shared/` |
| Registry | Không | `agent-registry.json` — model, tools, description per agent |

## 6. Rủi ro khi chuyển

1. **Mất coverage**: OLD 466 commands → NEW 119. 374 OLD-only phải giữ lại (Phase 04 đã plan).
2. **Prompt-inline vs engine-dispatch**: OLD commands hoạt động cả khi engine chết; NEW commands phụ thuộc `python3 -m src.main` — cần venv + deps.
3. **Hardcoded `/Users/macbook/mekong-cli`** còn sót trong NEW `_core/settings.json` (hooks.kits, mcp filesystem/sqlite args) — phải sửa khi migrate.
4. **OpenCode song song**: OLD có cả hệ `.opencode/` 870 commands + opencode.json; NEW gần như bỏ — user dùng OpenCode sẽ mất surface nếu không giữ.
5. **Env token**: OLD env chứa live ANTHROPIC_AUTH_TOKEN (localhost:20128 gateway); NEW env mặc định trỏ claude-api.zunef.com — merge sai là mất kết nối.

## Kết luận

OLD = **hệ prompt-centric**: thông minh nằm trong .md files, nhiều, tự do, nhưng trùng lặp, hardcode path, và dual-CLI chỉ là spawn subprocess mất harness.

NEW = **hệ harness-centric**: thông tin tập trung vào engine Python + catalog, commands trở thành thin dispatchers, hooks/state/statusline chia sẻ lib chung, model routing theo command, portable `$CLAUDE_PROJECT_DIR`. Đây là bước hiện thực hóa đúng DESIGN_DUAL_CLI.md (single process, shared harness core) mà OLD chỉ mới viết thiết kế.

## Unresolved questions
- Có giữ hệ `.opencode/` (870 commands) của OLD không, hay chuẩn bị về một mình Claude Code?
- 374 OLD-only commands: giữ nguyên dạng prompt-inline hay dần port sang engine-dispatch?
- Env nào là đích cuối: localhost:20128 gateway (OLD) hay zunef cloud (NEW)?
