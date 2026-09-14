# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""i18n strings for build CLI."""

from __future__ import annotations

_VI: dict[str, str] = {
    "no_spec": "Không tìm thấy .mekong/SPEC_OUTPUT.md. Chạy `mekong plan from-init` trước.",
    "no_spec_hint": "Chạy `mekong plan from-init` trước.",
    "no_domains": "Không tìm thấy từ khóa lĩnh vực trong SPEC_OUTPUT.md.",
    "no_domains_hint": "SPEC có thể không chứa domain outlines theo format backtick hoặc bullet.",
    "already_exists": ".mekong/TASKS.todo đã tồn tại. Dùng --force để ghi đè.",
    "tasks_generated": "Công việc Build đã tạo",
    "dry_run": "Mô phỏng — không ghi tệp.",
    "dry_run_header": "Sẽ tạo:",
    "dry_run_tasks_file": ".mekong/TASKS.todo với các công việc sau:",
    "dry_run_total": "Tổng: {total} công việc trên {domains} lĩnh vực.",
}

_EN: dict[str, str] = {
    "no_spec": ".mekong/SPEC_OUTPUT.md not found. Run `mekong plan from-init` first.",
    "no_spec_hint": "Run `mekong plan from-init` first.",
    "no_domains": "No domain keywords found in SPEC_OUTPUT.md.",
    "no_domains_hint": "The spec may not contain backtick-quoted or bullet-prefixed outlines.",
    "already_exists": ".mekong/TASKS.todo already exists. Use --force to overwrite.",
    "tasks_generated": "Build Tasks Generated",
    "dry_run": "Dry run — no files written.",
    "dry_run_header": "Would generate:",
    "dry_run_tasks_file": ".mekong/TASKS.todo with the following tasks:",
    "dry_run_total": "Total: {total} tasks across {domains} domains.",
}

MESSAGES = {"en": _EN, "vi": _VI}


def get_messages(locale: str) -> dict[str, str]:
    locale = locale if locale in ("en", "vi") else "en"
    return MESSAGES.get(locale, _EN)


DEFAULT_LOCALE = "en"


def t(locale: str, key: str, default: str = "") -> str:
    return get_messages(locale).get(key) or get_messages(DEFAULT_LOCALE).get(key) or default
