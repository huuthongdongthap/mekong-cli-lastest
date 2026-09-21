# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""i18n prompt strings for the company-init Typer CLI commands.

PROMPT_EN  — fully translated English strings.
PROMPT_VI  — Vietnamese translations (natural business Vietnamese, not
             machine-translated).  Untranslated entries carry the
             ``[VI TBD:<key>]`` sentinel so ``grep "VI TBD"`` surfaces
             every missing string immediately.

Also re-exports backward-compatible single-key shortcuts
(q1_name, q2_prompt, …) under the MESSAGES lookup used by the CLI.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# English (complete)
# ---------------------------------------------------------------------------
PROMPT_EN: dict[str, str] = {
    # ── wizard questions ──────────────────────────────────────────────────
    "q1_company_name":  "Company name",
    "q1_name":          "Company name",          # compat alias
    "q2_product_type":  "Product type (1—4)",
    "q2_header":        "Choose product type",
    "q2_prompt":        "Product type (1—4)",    # compat alias
    "q3_scenario":      "Deployment scenario (1—4)",
    "q3_header":        "Choose deployment scenario",
    "q3_prompt":        "Scenario (1—4)",        # compat alias
    "q4_budget":        "Budget tier (1—4)",
    "q4_header":        "Choose budget tier",
    "q4_prompt":        "Budget tier (1—4)",     # compat alias
    "q5_language":      "Primary language (1—3)",
    "q5_header":        "Choose primary language",
    "q5_prompt":        "Language (1—3)",        # compat alias

    # ── status / completion ───────────────────────────────────────────────
    "init_complete":    "Company initialized successfully.",
    "files_written":    "Files written to .mekong/",
    "already_initialized": "Already initialized",
    "company_status":   "Company Status",
    "status_name":      "Name",
    "status_product":   "Product",
    "status_scenario":  "Scenario",
    "status_budget":    "Budget",
    "status_lang":      "Language",
    "status_mcu":       "MCU Credits",

    # ── reset ─────────────────────────────────────────────────────────────
    "reset_confirm":    "This will DELETE .mekong/ and re-run the wizard. Continue?",
    "reset_done":       "Company re-initialized.",

    # ── errors ────────────────────────────────────────────────────────────
    "error_generic":    "Init failed:",

    # ── misc consumed by __init__.py ─────────────────────────────────────
    "welcome":      "Welcome to Mekong — Company Init",
    "confirm":      "Write config to .mekong/?",
    "already_setup": "Run `mekong company reset --force` to reconfigure.",
    "no_company":   "No .mekong/company.json found.",
    "reset_preview":    "Current company configuration "
                       "(reset without --force is read-only):",
    "reset_force_hint": "Re-run with --force to wipe and re-init.",
    "error":       "Init failed",             # alias kept for compat

    # ── dry-run preview ──────────────────────────────────────────────────
    "dry_run_preview":  "[DRY RUN] Preview only — no files will be written.",
    "dry_run_target":   "Target directory",
    "dry_run_files":    "Files that would be created",
    "dry_run_company_json": "company.json",
    "dry_run_agents":   "agents/ (8 role prompts)",
    "dry_run_manifests": "manifests/",
    "dry_run_metrics":  "metrics/",
    "dry_run_notice":   "Run without --dry-run to scaffold.",
    "dry_run_hint":     "Tip: use `ak init` (or `/ak:init`) for AgentKit ownership tracking.",
}

# ---------------------------------------------------------------------------
# Vietnamese (complete — natural business register)
# ---------------------------------------------------------------------------
PROMPT_VI: dict[str, str] = {
    # ── wizard questions ──────────────────────────────────────────────────
    "q1_company_name":  "Tên công ty",
    "q1_name":          "Tên công ty",
    "q2_product_type":  "Loại sản phẩm (1 — 4)",
    "q2_header":        "Chọn loại sản phẩm",
    "q2_prompt":        "Loại sản phẩm (1 — 4)",
    "q3_scenario":      "Kịch bản triển khai (1 — 4)",
    "q3_header":        "Chọn kịch bản triển khai",
    "q3_prompt":        "Kịch bản (1 — 4)",
    "q4_budget":        "Ngân sách (1 — 4)",
    "q4_header":        "Chọn ngân sách",
    "q4_prompt":        "Ngân sách (1 — 4)",
    "q5_language":      "Ngôn ngữ chính (1 — 3)",
    "q5_header":        "Chọn ngôn ngữ chính",
    "q5_prompt":        "Ngôn ngữ (1 — 3)",

    # ── status / completion ───────────────────────────────────────────────
    "init_complete":    "Khởi tạo công ty thành công.",
    "files_written":    "Đã ghi tập tin vào .mekong/",
    "already_initialized": "Đã khởi tạo trước đó",
    "company_status":   "Trạng thái công ty",
    "status_name":      "Tên công ty",
    "status_product":   "Sản phẩm",
    "status_scenario":  "Kịch bản",
    "status_budget":    "Ngân sách",
    "status_lang":      "Ngôn ngữ",
    "status_mcu":       "Tín dụng MCU",

    # ── reset ─────────────────────────────────────────────────────────────
    "reset_confirm":    "Thao tác này sẽ XÓA thư mục .mekong/ và "
                       "chạy lại toàn bộ wizard. Bạn có muốn tiếp tục?",
    "reset_done":       "Đã khởi tạo lại công ty.",

    # ── errors ────────────────────────────────────────────────────────────
    "error_generic":    "Khởi tạo thất bại:",

    # ── misc consumed by __init__.py ─────────────────────────────────────
    "welcome":          "Chào mừng đến Mekong — Khởi tạo Công ty",
    "confirm":          "Ghi cấu hình vào .mekong/?",
    "already_setup":    "Chạy `mekong company reset --force` để cấu hình lại.",
    "no_company":       "Không tìm thấy .mekong/company.json.",
    "reset_preview":    "Cấu hình hiện tại "
                       "(reset không --force chỉ hiện thị, không ghi đè):",
    "reset_force_hint": "Chạy lại với --force để xóa và khởi tạo lại.",
    "error":            "Khởi tạo thất bại",   # compat alias

    # ── dry-run preview ──────────────────────────────────────────────────
    "dry_run_preview":  "[CHẠY THỬ] Chỉ xem trước — không ghi tập tin.",
    "dry_run_target":   "Thư mục đích",
    "dry_run_files":    "Tập tin sẽ tạo",
    "dry_run_company_json": "company.json",
    "dry_run_agents":   "agents/ (8 hồ sơ vai trò)",
    "dry_run_manifests": "manifests/",
    "dry_run_metrics":  "metrics/",
    "dry_run_notice":   "Chạy không --dry-run để tạo cấu hình.",
    "dry_run_hint":     "Mẹo: dùng `ak init` (hoặc `/ak:init`) cho theo dõi quyền sở hữu AgentKit.",
}

# ---------------------------------------------------------------------------
# Lookup helpers (used by CLI __init__.py)
# ---------------------------------------------------------------------------
MESSAGES: dict[str, dict[str, str]] = {
    "en": PROMPT_EN,
    "vi": PROMPT_VI,
}

DEFAULT_LOCALE: str = "en"


def get_messages(locale: str) -> dict[str, str]:
    """Return message bundle for *locale*, falling back to English."""
    return MESSAGES.get(locale) or MESSAGES[DEFAULT_LOCALE]


def t(locale: str, key: str, default: str = "") -> str:
    """Return a single translated string; falls back to English, then *default*."""
    return get_messages(locale).get(key) or get_messages(DEFAULT_LOCALE).get(key) or default
