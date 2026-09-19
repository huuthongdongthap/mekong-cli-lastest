# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Plan CLI — ``mekong plan from-init``.

Reads ``.mekong/company.json`` (produced by ``mekong company init``) and
generates:
- ``.mekong/SPEC_OUTPUT.md`` — product spec outline /domain logic
- ``./plans/<company>-<date>-<slug>/plan.md`` — actionable plan with phases,
  dependencies, acceptance criteria, and per-phase file links

This command depends on the Mekong company-config wizard output — it is NOT
an AgentKit command and does NOT interact with ``.agentkit/``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.cli.commands.plan import i18n as i18n_mod
from src.cli.commands.plan.spec_templates import render_data_model, render_quickstart, render_research

# ---------------------------------------------------------------------------
# Typer sub-app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="plan",
    help="Generate plan from company init",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()

DEFAULT_LOCALE = "en"

# ---------------------------------------------------------------------------
# Product-type → domain outline (template support blocks)
# ---------------------------------------------------------------------------

_DOMAIN_OUTLINES: dict[str, dict[str, list[str]]] = {
    "saas": {
        "en": [
            "User authentication & authorization (SSO, RBAC)",
            "Subscription billing & invoicing (Stripe / NOWPayments / PayOS)",
            "REST / GraphQL API layer with rate limiting",
            "Usage analytics & quota enforcement",
            "Admin dashboard & team management",
            "Email notification pipeline",
            "Audit log & compliance reporting",
        ],
        "vi": [
            "Xác thực & ủy quyền người dùng (SSO, RBAC)",
            "Thanh toán đăng ký & hóa đơn (Stripe / NOWPayments / PayOS)",
            "API REST / GraphQL với giới hạn tần suất",
            "Phân tích sử dụng & kiểm tra hạn mức",
            "Bảng điều khiển quản trị & quản lý nhóm",
            "Pipeline thông báo email",
            "Nhật ký kiểm toán & báo cáo tuân thủ",
        ],
    },
    "ecommerce": {
        "en": [
            "Product catalog & inventory management",
            "Shopping cart & checkout flow",
            "Payment gateway integration (multiple providers)",
            "Order management & fulfillment tracking",
            "Customer accounts & order history",
            "Discount / coupon system",
            "Shipping rate calculation & tracking",
            "SEO & product feed",
        ],
        "vi": [
            "Danh mục sản phẩm & quản lý tồn kho",
            "Giỏ hàng & luồng thanh toán",
            "Tích hợp cổng thanh toán (nhiều nhà cung cấp)",
            "Quản lý đơn hàng & theo dõi thực hiện",
            "Tài khoản khách hàng & lịch sử đơn hàng",
            "Hệ thống giảm giá / mã coupon",
            "Tính toán & theo dõi cước vận chuyển",
            "SEO & nguồn cấp sản phẩm",
        ],
    },
    "digital": {
        "en": [
            "Content management (CRUD for digital assets)",
            "File storage & delivery (CDN / R2)",
            "Subscription access control (tier gating)",
            "Download & streaming serving",
            "User library / collection management",
            "Payment & license key delivery",
            "Content versioning & updates",
        ],
        "vi": [
            "Quản lý nội dung (CRUD cho tài sản số)",
            "Lưu trữ & phân phối tệp (CDN / R2)",
            "Kiểm soát truy cập đăng ký (tier gating)",
            "Dịch vụ tải xuống & phát trực tuyến",
            "Thư viện / quản lý bộ sưu tập người dùng",
            "Giao hàng thanh toán & khóa bản quyền",
            "Phiên bản & cập nhật nội dung",
        ],
    },
    "api_service": {
        "en": [
            "OpenAPI / AsyncAPI spec design",
            "API gateway & rate limiting",
            "SDK generation (Python, Node, Go)",
            "Usage metering & billing per call",
            "Webhook delivery system",
            "Developer portal & API key management",
            "SLA monitoring & uptime reporting",
        ],
        "vi": [
            "Thiết kế spec OpenAPI / AsyncAPI",
            "Cổng API & giới hạn tần suất",
            "Tạo SDK (Python, Node, Go)",
            "Đo lường sử dụng & thanh toán theo lời gọi",
            "Hệ thống giao webhook",
            "Cổng nhà phát triển & quản lý API key",
            "Giám sát SLA & báo cáo thời gian hoạt động",
        ],
    },
    "consulting": {
        "en": [
            "Client profile & engagement management",
            "Proposal generation & e-signature",
            "Scheduling & calendar integration",
            "Project tracking & milestone reporting",
            "Time tracking & invoicing",
            "Knowledge base & resource library",
            "Client portal & progress dashboard",
        ],
        "vi": [
            "Hồ sơ khách hàng & quản lý hợp tác",
            "Tạo đề xuất & chữ ký điện tử",
            "Lên lịch & tích hợp lịch",
            "Theo dõi dự án & báo cáo cột mốc",
            "Theo dõi thời gian & hóa đơn",
            "Cơ sở tri thức & thư viện tài nguyên",
            "Cổng khách hàng & bảng theo dõi tiến độ",
        ],
    },
}

# ---------------------------------------------------------------------------
# Phase definitions — shared across product types (lightweight, language-switch)
# ---------------------------------------------------------------------------

_PHASES: dict[str, dict[str, dict[str, str]]] = {
    "research": {
        "en": {"title": "Research", "acceptance": "Requirements documented; tech stack chosen"},
        "vi": {"title": "Nghiên cứu", "acceptance": "Yêu cầu được lưu; stack công nghệ đã chọn"},
    },
    "implement": {
        "en": {"title": "Implement", "acceptance": "All features pass lint, type-check, unit tests"},
        "vi": {"title": "Triển khai", "acceptance": "Tính năng pass lint, type-check, unit test"},
    },
    "test": {
        "en": {"title": "Test", "acceptance": "Test coverage >= 80%; CI green"},
        "vi": {"title": "Kiểm thử", "acceptance": "Độ phủ test >= 80%; CI xanh"},
    },
    "review": {
        "en": {"title": "Review", "acceptance": "Code reviewed; security audit passed"},
        "vi": {"title": "Đánh giá", "acceptance": "Code đã review; kiểm tra bảo mật pass"},
    },
    "deploy": {
        "en": {"title": "Deploy", "acceptance": "Production deploy green; SHA verified"},
        "vi": {"title": "Triển khai", "acceptance": "Triển khai production xanh; SHA đã xác minh"},
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    """Return a URL-safe slug; preserves spaces (already lowercased)."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _load_company(base_dir: Path) -> Optional[dict]:
    p = base_dir / ".mekong" / "company.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _domain_outlines(product_type: str, lang: str) -> list[str]:
    return _DOMAIN_OUTLINES.get(product_type, {}).get(lang, _DOMAIN_OUTLINES.get(product_type, {}).get("en", []))


# ---------------------------------------------------------------------------
# Spec output generation
# ---------------------------------------------------------------------------


def _generate_spec(company: dict, outlines: list[str], lang: str) -> str:
    """Return SPEC_OUTPUT.md content (deterministic template)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    is_vi = lang == "vi"

    header = "# Product Spec\n\n" if not is_vi else "# Đặc tả sản phẩm\n\n"
    meta = (
        f"**Company:** {company.get('company_name', '?')}  \n"
        f"**Product Type:** {company.get('product_type', '?')}  \n"
        f"**Generated:** {now}\n\n"
    )
    separator = "---\n\n"

    overview_title = "## Overview\n\n" if not is_vi else "## Tổng quan\n\n"
    context = (
        f"Auto-generated from `mekong company init` for **{company.get('product_type', '?')}** product.  \n"
        f"Scenario: `{company.get('scenario', '?')}` | Budget: `{company.get('budget_tier', '?')}`.\n\n"
    )

    domains_title = "## Domains\n\n" if not is_vi else "## Lĩnh vực\n\n"
    domains = "".join(f"- `{d}`\n" for d in outlines) + "\n"

    return header + meta + separator + overview_title + context + separator + domains_title + domains


# ---------------------------------------------------------------------------
# plan.md generation (target: ./plans/<company>-<date>/plan.md)
# ---------------------------------------------------------------------------


def _generate_plan_md(
    company: dict,
    outlines: list[str],
    lang: str,
) -> tuple[str, Path]:
    """Return (plan_content, plan_dir)."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    company_name = company.get("company_name", "project")
    slug = _slug(company_name)

    plans_root = Path("plans")
    plan_dir = plans_root / f"{slug}-{date_str}"
    plan_dir.mkdir(parents=True, exist_ok=True)

    phases = [
        {"key": "research", "title": "Research" if lang != "vi" else "Nghiên cứu"},
        {"key": "implement", "title": "Implement" if lang != "vi" else "Triển khai"},
        {"key": "test", "title": "Test" if lang != "vi" else "Kiểm thử"},
        {"key": "review", "title": "Review" if lang != "vi" else "Đánh giá"},
        {"key": "deploy", "title": "Deploy" if lang != "vi" else "Triển khai"},
    ]
    if lang == "vi":
        phases = [
            {"key": "research", "title": "Nghiên cứu"},
            {"key": "implement", "title": "Triển khai"},
            {"key": "test", "title": "Kiểm thử"},
            {"key": "review", "title": "Đánh giá"},
            {"key": "deploy", "title": "Triển khai"},
        ]

    # Build phase links
    phase_links: list[str] = []
    dep_lines: list[str] = []

    for idx, phase in enumerate(phases):
        phase_file = plan_dir / f"phase-{idx + 1:02d}-{phase['key']}.md"
        phase_links.append(f"[phase-{idx + 1:02d}]({phase_file.name})")
        if idx > 0:
            dep_lines.append(f"- phase-{idx:02d} -> phase-{idx + 1:02d}")

    # Build acceptance criteria (per-domain)
    ac_lines: list[str] = []
    for i, outline in enumerate(outlines, 1):
        ac_lines.append(f"{i}. **{outline}** — implemented, tested, reviewed")

    is_vi = lang == "vi"
    title_line = "# Plan\n" if not is_vi else "# Kế hoạch\n"
    meta = (
        f"**Company:** {company.get('company_name', '?')}  \n"
        f"**Product:** {company.get('product_type', '?')}  \n"
        f"**Status:** planned  \n"
        f"**Created:** {now.strftime('%Y-%m-%d')}\n\n"
    )

    sep = "---\n\n"
    phases_title = "## Phases\n\n"
    phases_list_parts = []
    for p, link in zip(phases, phase_links):
        url = link.split("](")[1].rstrip(")")
        phases_list_parts.append(f"- **{p['title']}** ([{link}]({url}))")
    phases_list = "\n".join(phases_list_parts) + "\n\n"

    deps_title = "## Dependencies\n\n"
    deps_content = "\n".join(dep_lines) + "\n\n" if dep_lines else "Sequential — no parallel track required.\n\n"

    ac_title = "## Acceptance Criteria\n\n"
    ac_content = "\n".join(ac_lines) + "\n"

    plan_content = title_line + meta + sep + phases_title + phases_list + deps_title + deps_content + ac_title + ac_content

    # Write plan.md
    plan_file = plan_dir / "plan.md"
    plan_file.write_text(plan_content, encoding="utf-8")

    # Write stub phase files (headers only — real content filled by /cook)
    phase_stub_templates = {
        "research": "## Context links\n\n## Requirements\n\n## Files to modify/create/delete\n\n## Implementation steps\n\n## Tests or validation\n\n## Risks and rollback notes\n",
        "implement": "## Context links\n\n## Requirements\n\n## Files to modify/create/delete\n\n## Implementation steps\n\n## Tests or validation\n\n## Risks and rollback notes\n",
        "test": "## Context links\n\n## Test plan\n\n## Coverage targets\n\n## CI requirements\n",
        "review": "## Context links\n\n## Review checklist\n\n## Security audit\n\n## Approvals\n",
        "deploy": "## Context links\n\n## Pre-flight checks\n\n## Deployment steps\n\n## Smoke tests\n\n## Rollback plan\n",
    }

    for idx, phase in enumerate(phases):
        phase_file = plan_dir / f"phase-{idx + 1:02d}-{phase['key']}.md"
        stub = f"# Phase {idx + 1:02d}: {phase['title']}\n\n"
        stub += f"**Acceptance:** {phase.get('acceptance', 'TBD')}\n\n"
        stub += phase_stub_templates.get(phase["key"], "\n")
        phase_file.write_text(stub, encoding="utf-8")

    return plan_content, plan_dir


# ---------------------------------------------------------------------------
# SDD multi-artifact helpers
# ---------------------------------------------------------------------------


def _write_artifacts(plan_dir: Path, company: dict, lang: str) -> None:
    """Write 4 supplementary SDD artifacts. Each write independently guarded."""
    # a. contracts/api-spec.json — minimal OpenAPI skeleton
    try:
        api_spec = {
            "openapi": "3.0.3",
            "info": {
                "title": company.get("company_name", "Project"),
                "version": "0.1.0",
                "description": "Auto-generated API skeleton.",
            },
            "paths": {},
        }
        (plan_dir / "contracts").mkdir(exist_ok=True)
        (plan_dir / "contracts" / "api-spec.json").write_text(
            json.dumps(api_spec, indent=2), encoding="utf-8",
        )
    except OSError:
        pass

    # b–d. Markdown artifacts via spec_templates.render
    md_artifacts = {
        "data-model.md": render_data_model,
        "quickstart.md": render_quickstart,
        "research.md": render_research,
    }
    for filename, render_fn in md_artifacts.items():
        try:
            (plan_dir / filename).write_text(render_fn(company, lang), encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# `from-init` command
# ---------------------------------------------------------------------------


@app.command("from-init")
def from_init_cmd(
    output_dir: Path = typer.Option(
        Path("."),
        "--dir",
        "-d",
        exists=False,
        file_okay=False,
        dir_okay=True,
        help="Project root (default: CWD).",
    ),
    lang: str = typer.Option(
        DEFAULT_LOCALE,
        "--lang",
        help="Output language: en | vi.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing SPEC_OUTPUT.md and plans/.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview spec path and planned plan directory without writing files.",
    ),
) -> None:
    """Generate spec and plan from .mekong/company.json.

    Writes:
    - .mekong/SPEC_OUTPUT.md (product spec outline)
    - ./plans/<company>-<date>/plan.md (+ phase stub files)

    Use ``--dry-run`` to preview the planned spec path and plan directory
    without mutating disk.
    """
    path = output_dir.resolve()
    company = _load_company(path)
    if company is None:
        msg = i18n_mod.t(lang, "no_company", ".mekong/company.json not found. Run `mekong company init` first.")
        console.print(f'[yellow]{msg}[/]')
        raise typer.Exit(code=1)

    # Validate lang
    if lang not in ("en", "vi"):
       _msg1 = f"Invalid --lang: {lang}. Use en | vi."
       console.print(f'[red]{i18n_mod.t(lang, "invalid_lang", _msg1)}[/]')
       raise typer.Exit(code=1)

    product_type = company.get("product_type", "saas")
    outlines = _domain_outlines(product_type, lang)
    if not outlines:
       _msg2 = f"No domain outline for product_type '{product_type}'. Using generic."
       console.print(f'[yellow]{i18n_mod.t(lang, "no_domains_hint", _msg2)}[/]')
       outlines = ["Core platform features"]

    # Check pre-existing files
    spec_path = path / ".mekong" / "SPEC_OUTPUT.md"
    plans_root = path / "plans"

    # --dry-run preview: print planned spec path + plan dir, exit 0
    if dry_run:
        slug = _slug(company.get("company_name", "project"))
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        plan_dir_preview = plans_root / f"{slug}-{date_str}"
        console.print("[bold yellow][DRY RUN][/] Preview only — nothing written.\n")
        console.print(f"  company:    [cyan]{company.get('company_name', '?')}[/]")
        console.print(f"  product:    [cyan]{product_type}[/]")
        console.print(f"  spec_path:  [cyan]{spec_path}[/]")
        console.print(f"  plan_dir:   [cyan]{plan_dir_preview}[/]")
        console.print(f"  domains:    [cyan]{len(outlines)}[/]")
        console.print("\n[dim]Run without --dry-run to generate spec + plan.[/]")
        raise typer.Exit(code=0)

    if not force and spec_path.exists():
        _msg3 = f"SPEC_OUTPUT.md already exists at {spec_path}. Use --force to overwrite."
        console.print(f'[yellow]{i18n_mod.t(lang, "spec_exists", _msg3)}[/]')
        raise typer.Exit(code=1)
    if not force and plans_root.exists() and any(plans_root.iterdir()):
        _msg4 = "plans/ directory already has content. Use --force to overwrite."
        console.print(f'[yellow]{i18n_mod.t(lang, "plans_exist", _msg4)}[/]')
        raise typer.Exit(code=1)

    # Clean existing plan dir if force
    if force and plans_root.exists():
        for item in plans_root.iterdir():
            if item.is_dir():
                import shutil
                shutil.rmtree(item, ignore_errors=True)

    # Generate spec
    spec_content = _generate_spec(company, outlines, lang)
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(spec_content, encoding="utf-8")

    # Generate plan.md + phase stubs
    plan_content, plan_dir = _generate_plan_md(company, outlines, lang)

# Write supplementary SDD artifacts (independently guarded)
    _write_artifacts(plan_dir, company, lang)

    # Summary table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("key", style="cyan", no_wrap=True)
    table.add_column("value", style="green")
    table.add_row("company", company.get("company_name", "?"))
    table.add_row("product", product_type)
    table.add_row("spec", str(spec_path.relative_to(path)))
    table.add_row("plan_dir", str(plan_dir))
    table.add_row("domains", str(len(outlines)))

    panel = Panel(
        table,
        title=i18n_mod.t(lang, "plan_generated_title", "Plan Generated"),
        border_style="green",
        expand=False,
    )
    console.print(panel)
