# Hallmark → Mekong Comparison Matrix

> Bước 0 — Hallmark Deep Integration. Nguồn: clone `/tmp/hallmark-inspect` (nutlope/hallmark, MIT, v1.1.0).
> SKILL.md: 558 dòng. Toàn bộ skill: 9.752 dòng markdown (SKILL.md + references/ gồm 21 macrostructures, 5 themes, 4 genres, 50 component archetypes, slop-test, study, verbs, design-md, custom-theme...).
> Slop-test: **58 gates** + pre-emit self-critique 6 trục (Philosophy / Hierarchy / Execution / Specificity / Restraint / Variety), xác nhận trực tiếp trong `references/slop-test.md`.
> Nguyên tắc: adapt, don't transplant — chiết thành data/schema/check tự động, prompt viết lại theo nguyên lý, attribution MIT đầy đủ.

## Matrix

| # | Hallmark capability | Mechanism (cách Hallmark làm) | Value cho Mekong | Mekong equivalent | Verdict | Lý do |
|---|---|---|---|---|---|---|
| 1 | 58 slop-test gates | Checklist post-emit, mỗi gate là câu hỏi yes/no + genre override inline | Lõi của quality gate — chuyển được thành deterministic checks + LLM judge | Chưa có — sẽ là `knowledge/gates.yaml` + `gates.py` | **Keep (adapt)** | Giá trị cao nhất, đo được. Chuyển thành YAML có id/category/severity/detection_method/pass_condition; chạy static regex trước, LLM chỉ cho heuristic/visual |
| 2 | Pre-emit self-critique 6 trục | Chấm 1–5 trước khi emit, <3 thì revision pass, stamp P/H/E/S/R/V | Ép chất lượng trước khi trả kết quả | Chưa có | **Keep (adapt)** | Gộp vào `scoring.py` như critic pass; giữ cơ chế ngưỡng <3 |
| 3 | 21 macrostructures | Index mỏng 1 dòng/macro → load đúng 1 file chi tiết; mỗi macro = fingerprint đầy đủ | Chống "hero→3 cards→CTA→footer" sameness; chọn nhanh, token rẻ | Chưa có | **Keep (adapt)** | Rút gọn thành `macrostructures.yaml` (name, when-to-use, axes, knobs), viết lại theo nguyên lý, không dịch 1:1 |
| 4 | Diversification rule + `.hallmark/log.json` | Đọc stamp/log trước khi pick; cấm trùng macro 3 lần gần nhất; theme phải khác ≥1/3 trục (paper band / display style / accent hue) | Đảm bảo variety giữa các lần chạy — đúng mục tiêu "mỗi sản phẩm một khác" | MemoryStore (`src/core/memory_canonical.py`) có sẵn | **Keep (adapt)** | Lưu design memory qua MemoryStore namespace `design:` + `.mekong/design/`; đảo ngược rule cho multi-page app (consistency thắng) |
| 5 | 4 genres (editorial / modern-minimal / atmospheric / playful) | Signal-based detection từ brief, silent default = editorial; genre scope theme cluster + gate overrides | Phân loại brief nhanh, giảm quyết định | Chưa có | **Keep (adapt)** | `genres.yaml` rút gọn; detection nhúng vào pipeline brief-parsing |
| 6 | 21 catalog themes + theme axis values | Theme = OKLCH palette + font pairing + 3 trục diversification ghi trong tokens.css | Seed palette chất lượng cao, tránh default tím-xanh | Chưa có | **Adapt** | Chỉ giữ cấu trúc trục + nguyên lý palette; không bưng nguyên 21 theme — sinh theme từ DNA/brief, giữ vài theme mẫu làm reference |
| 7 | Custom theme (tuned + bespoke) | 1 câu hỏi duy nhất (vibe 4–8 từ + anchor colour) → sinh OKLCH palette + font pairing | Sinh theme theo brand thật của user/Sophia | Chưa có | **Adapt** | Nhập vào pipeline build: brief → DNA → palette; bỏ nghi thức hội thoại, giữ thuật toán |
| 8 | `study` verb (image + URL mode) | 5-step protocol (Surface/Type/Structure/Motion/Rhythm) + structured-fields schema + refusal layer + junk-or-blocked detection | Trích Design DNA tái sử dụng — đúng Phase 11/12 (Sophia + memory) | BrowserAgent (`src/core/browser_agent.py`) cho URL fetch | **Keep (adapt)** | Thành `mekong ui study`; schema → pydantic DesignDNA; URL safety/refusal giữ nguyên; rhythm blind-spot ghi rõ trong report |
| 9 | `audit` verb | Đọc file → Tell/Where/Severity/Fix, group by severity, stamp-vs-page check, genre-aware, design.md drift check | Audit UI có cấu trúc, không cảm tính | Chưa có | **Keep (adapt)** | Thành `mekong ui audit` + DESIGN SCORE block; tách 3 tầng bằng chứng OBJECTIVE/HEURISTIC/OPINION |
| 10 | `redesign` verb | Preserve copy/IA/brand/route; đổi structural fingerprint; single-page vs multi-page flow; design.md-first cho app | Redesign an toàn, không phá codebase | Chưa có | **Keep (adapt)** | Thành `mekong ui redesign`; giữ nguyên tắc non-destructive + design.md-first |
| 11 | `design.md` locked system + exports (tokens.css / Tailwind @theme / DTCG / shadcn) | File = source of truth; diversification đảo ngược thành consistency; 4 export format | Design system portable cho Sophia + các app Mekong | Chưa có | **Keep (adapt)** | DesignDNA JSON (pydantic) là format chính; export markdown/css khi cần; `mekong ui approve` để lock |
| 12 | Pre-flight scan (6 signal sources) | Quét design.md → fonts → palette → motion stance → spacing → framework trước khi hỏi user | Tôn trọng hệ thống sẵn có của project target | Chưa có | **Adapt** | Thu gọn: phát hiện tokens/framework/tailwind trong target; không cần cache `.hallmark/preflight.json` phức tạp |
| 13 | Design-context gate (Audience/Use case/Tone) | Luôn hỏi 3 câu, cho phép "go ahead" để infer + công khai inference | Chống đoán mò brief | Chưa có | **Adapt** | Nhập vào DesignBrief schema; ở chế độ non-interactive (agent gọi) thì infer + ghi rõ trong report |
| 14 | Component-scope flow + 8-state discipline | Detect brief component-shaped; bắt buộc 8 states (default/hover/focus/active/disabled/loading/error/success) | Chuẩn chất lượng component | Chưa có | **Adapt** | Giữ 8-state checklist như gate trong gates.yaml; bỏ nghi thức demo-wrapper file |
| 15 | Honest-copy gate (gate 46) | Cấm bịa metric/testimonial; placeholder `—` + "metric to confirm" | Cực quan trọng cho sản phẩm thật (Sophia campaigns) | Chưa có | **Keep** | Gate heuristic trong gates.yaml + rule trong prompt build |
| 16 | Locked tokens / no mid-render improvisation (gate 48) | Mọi màu/font phải reference named token | Audit được bằng static check | Chưa có | **Keep** | Deterministic gate (regex hex/oklch ngoài :root) |
| 17 | Mobile non-negotiables (gates 34, 49–57) | overflow-x clip, minmax(0,1fr), overflow-wrap, no 2-line clickable text... | Check tĩnh được, giá trị thực cao | Chưa có | **Keep** | Phần lớn là deterministic regex/AST-lite — chạy trước, không tốn token |
| 18 | Contrast gates 40–41 (APCA/WCAG + ink-on-ink) | Pair color/background, threshold cụ thể, OKLCH pre-check | Accessibility đo được | Chưa có | **Keep (adapt)** | Static parse cặp màu khi có thể; LLM judge phần còn lại, kèm confidence |
| 19 | Stamp convention (`/* Hallmark · ... */`) | Comment đầu file CSS ghi macro/theme/genre + kết quả gates | Machine-readable provenance cho lần chạy sau | Chưa có | **Adapt** | Đổi thành `/* Mekong Design · ... */`, giữ format để change_detect + audit đọc được |
| 20 | Refusal layer (marketplace, signature work, attestation) | Refuse list domain + attestation (a)/(b)/(c) trước khi emit design.md | Legal/ethics an toàn | Chưa có | **Keep (adapt)** | Giữ domain refuse-list + attestation trong `study`; ghi vào docs |
| 21 | Remote URL safety (SSRF guard) | Cấm IP literal/private range/non-web scheme; treat fetched content as untrusted | Bảo mật khi study URL | Chưa có | **Keep** | Bắt buộc trong visual.py/study — không được bỏ |
| 22 | Token-budget loading discipline (index-then-pick) | Chỉ load file reference cần thiết | Giảm chi phí token | Không cần — knowledge là YAML, code load có chọn lọc | **Reject (upstream-only)** | Là tối ưu cho context-window LLM của skill; Mekong load data bằng code, không áp dụng |
| 23 | Demo site + Vercel deploy (`site/`, examples, `_tests/` fixtures) | Showcase site để demo theme | Không phải intelligence | Không cần | **Reject (upstream-only)** | Chỉ là demo/marketing; chỉ tái dùng ý tưởng fixture tốt/xấu làm benchmark seeds (Bước 6), không lấy site |
| 24 | `npx skills` packaging / skill distribution | Đóng gói thành Claude/Cursor skill | Không áp dụng — Mekong là CLI Typer | Không cần | **Reject (upstream-only)** | Mekong phân phối qua PyInstaller/release, không phải skill package |
| 25 | Press-T theme cycling UI + interactive demo pages | UI demo để người dùng thử theme | Demo, không phải intelligence | Không cần | **Reject (upstream-only)** | Không nằm trong giá trị cốt lõi; theme chọn qua DNA/brief |
| 26 | Conversational rituals (hỏi 3 câu, "lock the system" phrases, CTA lines, preview block format) | Nghi thức hội thoại chat-assistant | UX chat, không hợp CLI | CLI flags + report thay thế | **Reject (upstream-only)** | Mekong chạy command/agent — thay bằng flags, JSON output, DESIGN SCORE block |
| 27 | `.hallmark/log.json` file format cụ thể | JSON array append ở project root | Trùng với memory layer sẵn có | MemoryStore | **Reject (format) / Keep (ý tưởng)** | Không dùng file format của Hallmark; ý tưởng rotation giữ qua MemoryStore (mục 4) |

## Tổng kết verdict

- **Keep / Keep (adapt):** 17 mục — slop gates, self-critique, macrostructures, diversification, genres, study, audit, redesign, design.md, honest-copy, locked tokens, mobile gates, contrast, refusal, SSRF guard...
- **Adapt:** 6 mục — themes, custom theme, pre-flight, design-context gate, component-scope, stamp.
- **Reject / Upstream-only:** 5 mục — (22) token-loading discipline, (23) demo site/Vercel, (24) npx skills packaging, (25) press-T theme cycling UI, (26) conversational rituals (+ mục 27 reject format cụ thể của log.json).

## Evidence kiểm tra tên lệnh

- `grep 'name="ui"' src/cli/app_setup.py` → **0 kết quả** (tên `ui` còn trống).
- `src/cli/command_surface.py` → **không tồn tại** (không cần kiểm tra thêm).
- `grep -rn 'name="ui"' src/` → 0 kết quả trên toàn bộ `src/`.
- `name="design"` đã bị chiếm tại `src/cli/app_setup.py:147` (SDLC design phase) → khẳng định dùng `mekong ui`.
