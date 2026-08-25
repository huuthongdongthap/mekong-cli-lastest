# Phase 02: settings.json Merge — FINAL ENV = ZUNEF CLOUD

## Overview
Merge OLD `~/.claude/settings.json` with NEW `.claude/_core/settings.json`
into one canonical `~/.claude/settings.json`. **Final env = Zunef**
(`https://claude-api.zunef.com/v1/ai`) per user decision 2026-08-24.
Localhost:20128 gateway giữ lại làm **fallback provider**, không phải đích.

## Priority
P0 — blocking. CC CLI reads settings.json at startup.

## Status
pending (updated with final-env decision)

## Env Discovery (verified 2026-08-24)

| Nguồn | BASE_URL | Models | Ghi chú |
|-------|----------|--------|---------|
| OLD `~/.claude/settings.json` | `http://localhost:20128` | `pmv-balance`, `pmv/fable-5`, `pmv/sonnet-5`, `pmv/claude-opus-4.8` | Gateway cục bộ, đang hoạt động |
| `~/.claude/settings-zunef.json` | `http://localhost:20128` | pmv/* | Wrapper `claude-zunef` dùng cái này |
| NEW `.claude/_core/settings.json` env | `https://claude-api.zunef.com/v1/ai` | — | Trỏ thẳng zunef cloud |
| NEW `modelRouting.providers.zunef` | `https://claude-api.zunef.com/v1/ai` | fable-5/sonnet-5-0/opus-4-x/haiku-4-5 | 15 rules match theo tên command |
| NEW `modelRouting.providers.ollama` | `http://localhost:11434/v1` | qwen3:35b-cc | Fallback priority 99 |

**Kết luận:** "Zunef" có 2 hình thức — cloud direct (NEW) và local gateway
pmv (OLD/current). Đích cuối chọn **cloud direct**; gateway pmv giữ làm
provider dự phòng trong modelRouting.

## Merge Decision Matrix (per-key)

### A. ENV — lấy từ NEW làm nền, vá từ OLD những key tinh hoa
```
GIỮ TỪ NEW (9 keys):
  LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_PROVIDER, LLM_TIMEOUT_MS   # engine Python dùng
  MEKONG_ENV=development, LOG_LEVEL=INFO
  ANTHROPIC_BASE_URL=https://claude-api.zunef.com/v1/ai               # ← ĐÍCH CUỐI
  API_TIMEOUT_MS=3000000

THÊM TỪ OLD (tinh hoa đã battle-tested, không có ở NEW):
  CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000        # NEW có 100000 → lấy 128000 (OLD lớn hơn)
  CLAUDE_CODE_AUTO_COMPACT_WINDOW=300000
  CLAUDE_CODE_EFFORT_LEVEL=ultracode
  CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
  CLAUDE_ENABLE_STREAM_WATCHDOG=1
  CLAUDE_STREAM_IDLE_TIMEOUT_MS=360000
  CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=90
  CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1

BỎ TỪ OLD (gắn với gateway pmv, không còn là đích):
  ANTHROPIC_AUTH_TOKEN (sk-627a...)           # → thay bằng zunef token (xem B)
  ANTHROPIC_MODEL=pmv-balance                 # → model: claude-fable-5 (từ NEW)
  ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL*  (6 keys pmv/*)  # → modelRouting rules lo hết
  CLAUDE_CODE_SUBAGENT_MODEL=pmv/sonnet-5     # → để default, routing theo rule
```

### B. AUTH — tách secret khỏi repo-config
```jsonc
// KHÔNG đặt token trực tiếp trong settings.json.
"modelRouting": {
  "providers": {
    "zunef": {
      "baseUrl": "https://claude-api.zunef.com/v1/ai",
      "apiKeyHelper": "~/.claude/scripts/get-zunef-token.sh",  // đọc từ keychain/file 600
      "timeoutMs": 3000000
    },
    "pmv-gateway": {                       // ← fallback giữ đường lui cũ
      "baseUrl": "http://localhost:20128",
      "apiKeyHelper": "~/.claude/scripts/get-pmv-token.sh",
      "timeoutMs": 3000000,
      "priority": 90
    },
    "ollama": {                            // ← offline fallback (từ NEW)
      "baseUrl": "http://localhost:11434/v1",
      "model": "qwen3:35b-cc",
      "apiKey": "ollama",
      "timeoutMs": 120000,
      "priority": 99
    }
  }
}
```
`get-zunef-token.sh`: `security find-generic-password -s mekong-zunef -w`
(lưu token vào Keychain một lần, không bao giờ nằm trong file config).

### C. HOOKS — NEW thắng toàn bộ, sửa 2 lỗi của NEW
NEW wiring (8 events) đúng sẵn với `$CLAUDE_PROJECT_DIR`. Phải vá trước khi áp dụng:
1. **Xóa** entry `mekong/hooks/brainstorm-vn-inject.cjs` — file KHÔNG tồn tại trong NEW repo (đã verify) → hook lỗi mỗi prompt.
2. Thay 3 path `/Users/macbook/mekong-cli` (mcp filesystem/git/sqlite args) → `$CLAUDE_PROJECT_DIR`.

OLD-only events mà NEW bỏ: `Stop(stop-checkpoint)`, `Notification(notify.cjs)`,
`TeammateIdle`, `PostToolUseFailure`, `PermissionRequest` — 4 event sau chỉ là
orca no-op passthrough (bỏ được). Giữ lại nếu cần: `stop-checkpoint.cjs`
(NEW _pipeline có file, chỉ thiếu wiring) → thêm vào Stop.

### D. PERMISSIONS — hợp nhất union, NEW bổ sung deny an toàn hơn
```
additionalDirectories = OLD ∪ NEW (dedupe)
allow = OLD allow list ∪ NEW allow list (union — OLD rộng hơn về test/lint)
deny  = NEW deny list (có .env protection + rm -rf guards mà OLD thiếu)
ask   = NEW ask list (git push/reset --hard/npm publish)
```

### E. MCP — NEW làm nền (filesystem/git/sqlite/memory), giữ stitch kit từ OLD
```
mcpServers = {
  filesystem, git, sqlite, memory   ← từ NEW (sửa path sang $CLAUDE_PROJECT_DIR)
  stitch, stitch-http, stitch-kit   ← từ OLD (đang hoạt động, có API key)
}
enableAllProjectMcpServers: true (giữ OLD)
```

### F. MODEL ROUTING — NEW 15 rules thắng nguyên khối
Rules match tên `mk-*` command → map đúng các model ID chuẩn zunef cloud.
OLD `modelRouter` (role-based flash/pro %) BỎ — thay bằng rules mới.
Giữ thêm key tương thích CC CLI: `model: claude-fable-5`,
`fallbackModel: claude-sonnet-5-0`.

### G. CÁC KEY BEHavior KHÁC — bảng quyết định
| Key | Giá trị cuối | Nguồn |
|-----|--------------|-------|
| statusLine.command | `$CLAUDE_PROJECT_DIR/.claude/_core/statusline.cjs` | NEW |
| outputStyle | coding-level-3-senior | cả hai giống nhau |
| includeCoAuthoredBy | false | cả hai |
| cleanupPeriodDays | 30 | cả hai |
| fastMode | true | NEW |
| ultracode/tui/theme/effort/autoMemory* | giữ từ OLD (runtime state người dùng) | OLD |
| hasCompletedOnboarding/autoUpdaterStatus/selectedModel | giữ OLD | OLD |
| disableWorkflows/enableWorkflows/workflowKeywordTriggerEnabled | giữ OLD | OLD |

## Precedence Hierarchy (nguyên tắc chống xung đột)
```
1. process.env (runtime)          — cao nhất, không đụng
2. ~/.claude/settings-zunef.json  — AUTH layer (token/baseUrl khi wrapper dùng)
3. ~/.claude/settings.json        — BEHAVIOR layer (merge kết quả này)
4. <repo>/.claude/settings.json   — project overrides (không tạo — tránh trùng)
```
Mỗi concern chỉ sống ở MỘT layer. Token không bao giờ ở layer 3/4.

## Steps
1. Chạy merge script theo Decision Matrix → `/tmp/merged-settings.json`
2. Diff review (`diff` old vs merged, lưu `/tmp/settings-diff.txt`)
3. Vá trước 2 lỗi NEW (brainstorm hook ref, macbook paths) TRƯỚC khi apply
4. Lưu zunef token vào Keychain + viết `get-zunef-token.sh`
5. Apply atomically: cp merged → `~/.claude/settings.json`
6. Validate (JSON parse + critical keys + hook resolve + smoke `claude --version`)

## Success Criteria
- [ ] JSON valid; `modelRouting.rules` ≥ 15; providers = {zunef, pmv-gateway, ollama}
- [ ] `env.ANTHROPIC_BASE_URL == https://claude-api.zunef.com/v1/ai`
- [ ] Không còn key `ANTHROPIC_AUTH_TOKEN` dạng literal trong settings.json
- [ ] Không còn string `/Users/macbook` trong settings.json
- [ ] Không còn hook trỏ tới file không tồn tại (validate-hooks.py exit 0)
- [ ] permissions.deny chứa `.env` protection + `rm -rf` guards
- [ ] mcpServers = {filesystem, git, sqlite, memory, stitch, stitch-http, stitch-kit}

## Rollback
```bash
cp ~/.claude/backups/migration-260821-2350/settings.json ~/.claude/settings.json
```

## Open Items (cần user/network xác nhận)
- Zunef cloud có chấp nhận đúng model ID `claude-fable-5`, `claude-sonnet-5-0`,
  `claude-opus-4-6[1m]`... như trong rules không → test 1 curl sau khi có token.
- Nếu zunef cloud down: fallback tự động qua pmv-gateway (priority 90) hay
  cần manual switch? (mặc định plan: auto-fallback theo priority).
