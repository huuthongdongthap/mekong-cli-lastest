# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Typer wrappers for the Vietnam business-funnel commands.

Reaches the existing library code in ``src/commands/zalo_oa.py``,
``src/commands/thue_dnvn.py``, ``src/commands/ke_toan.py``, and
``src/commands/sophia_video.py`` — which
already have unit tests — and exposes them as Typer sub-apps so the
``mekong`` binary can dispatch::

    mekong zalo-oa   send|broadcast|followers|caption|post
    mekong thue       tncn|tndn|gtgt
    mekong ke-toan    create|xml|journal|summary
    mekong tools video render|status|list|voices|avatars|templates|cost

Import paths used by ``src/cli/app_setup.py``::

    from src.cli.funnel_commands import ke_toan_app, thue_app, zalo_app, sophia_app
"""

from __future__ import annotations

import json
import os
from typing import Any

import typer

from src.commands.ke_toan import create_invoice
from src.commands.sophia_video import app as sophia_app
from src.commands.thue_dnvn import (
    calculate_gtgt,
    calculate_tncn,
    calculate_tndn,
)

__all__ = ["ke_toan_app", "sophia_app", "thue_app", "zalo_app"]

# ---------------------------------------------------------------------------
# Zalo OA
# ---------------------------------------------------------------------------

zalo_app = typer.Typer(
    name="zalo-oa",
    help="Zalo OA — gửi tin nhắn, broadcast, followers, caption, đăng bài",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)


def _zalo_client() -> Any:
    """Lazy factory mirroring src/commands/zalo_oa.py::_get_client()."""
    from integrations.zalo import ZaloOAClient

    token = os.getenv("ZALO_OA_ACCESS_TOKEN")
    app_id = os.getenv("ZALO_APP_ID", "")
    if not token:
        typer.echo("❌ Thiếu ZALO_OA_ACCESS_TOKEN. Đặt trong .env.", err=True)
        raise typer.Exit(code=1)
    return ZaloOAClient(access_token=token, app_id=app_id)


@zalo_app.command(name="send")
def zalo_send(
    user_id: str = typer.Argument(..., help="Zalo user ID"),
    message: str = typer.Argument(..., help="Nội dung tin nhắn"),
) -> None:
    """Gửi tin nhắn cá nhân qua Zalo OA."""
    client = _zalo_client()
    result = client.send_message(user_id, message)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@zalo_app.command(name="broadcast")
def zalo_broadcast(
    message: str = typer.Argument(..., help="Nội dung broadcast"),
) -> None:
    """Broadcast đến tất cả followers."""
    client = _zalo_client()
    result = client.broadcast(message)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@zalo_app.command(name="followers")
def zalo_followers(
    offset: int = typer.Option(0, "--offset", help="Vị trí bắt đầu"),
    count: int = typer.Option(50, "--count", help="Số lượng tối đa"),
) -> None:
    """Xem danh sách followers."""
    client = _zalo_client()
    result = client.get_followers(offset=offset, count=count)
    total = result.get("data", {}).get("total", 0)
    typer.echo(f"Tổng followers: {total:,}")
    for uid in result.get("data", {}).get("followers", []):
        typer.echo(f"  - {uid.get('user_id', '')} | {uid.get('display_name', '')}")


@zalo_app.command(name="caption")
def zalo_caption(
    product: str = typer.Argument(..., help="Tên sản phẩm/dịch vụ"),
    tone: str = typer.Option(
        "than_thien",
        "--tone",
        help="Giọng văn: than_thien | chuyen_nghiep | vui_ve",
    ),
) -> None:
    """Tạo caption marketing tự động (offline, không cần token)."""
    from integrations.zalo import generate_vn_caption

    typer.echo(generate_vn_caption(product=product, tone=tone))


@zalo_app.command(name="post")
def zalo_post(
    title: str = typer.Argument(..., help="Tiêu đề bài viết"),
    content: str = typer.Argument(..., help="Nội dung bài viết"),
    cover: str = typer.Option("", "--cover", help="URL ảnh bìa"),
) -> None:
    """Đăng bài viết lên Zalo OA."""
    client = _zalo_client()
    result = client.post_article(title=title, content=content, cover_image=cover)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Thuế VN
# ---------------------------------------------------------------------------

thue_app = typer.Typer(
    name="thue",
    help="Thuế VN — TNCN lũy tiến, TNDN, GTGT (offline, không cần API)",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)


@thue_app.command(name="tncn")
def thue_tncn(
    monthly_income: int = typer.Argument(..., help="Thu nhập gộp/tháng (VND)"),
    dependents: int = typer.Option(0, "--dependents", "-d", help="Số người phụ thuộc"),
) -> None:
    """Tính thuế TNCN lũy tiến (Điều 22, Luật thuế TNCN)."""
    typer.echo(calculate_tncn(monthly_income, dependents=dependents).to_summary())


@thue_app.command(name="tndn")
def thue_tndn(
    annual_revenue: int = typer.Argument(..., help="Doanh thu năm (VND)"),
) -> None:
    """Tính thuế TNDN (20% tiêu chuẩn, 17% SME ≤ 3 tỷ/năm)."""
    typer.echo(calculate_tndn(annual_revenue).to_summary())


@thue_app.command(name="gtgt")
def thue_gtgt(
    amount: int = typer.Argument(..., help="Số tiền trước thuế (VND)"),
    rate: int = typer.Option(10, "--rate", "-r", help="Thuế suất GTGT (5/8/10)"),
) -> None:
    """Tính thuế GTGT."""
    result = calculate_gtgt(amount, rate=rate)
    typer.echo(
        f"Cơ sở: {result['base_amount']:,} đ\n"
        f"Thuế GTGT ({result['vat_rate']}): {result['vat_amount']:,} đ\n"
        f"Tổng: {result['total_amount']:,} đ\n\n"
        f"⚠️  {result['disclaimer']}"
    )


# ---------------------------------------------------------------------------
# Kế Toán VN
# ---------------------------------------------------------------------------

ke_toan_app = typer.Typer(
    name="ke-toan",
    help="Kế toán VN — hóa đơn TT78/2021, bút toán VAS, XML",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)


@ke_toan_app.command(name="create")
def ke_toan_create(
    amount: int = typer.Argument(..., help="Số tiền trước thuế (VND)"),
    vat_rate: int = typer.Option(10, "--vat", help="Thuế suất GTGT (0/5/8/10)"),
    buyer: str = typer.Option(..., "--buyer", help="Tên người mua"),
    seller: str = typer.Option("Doanh Nghiệp", "--seller", help="Tên người bán"),
    seller_tax_code: str = typer.Option("0000000000", "--mst", help="Mã số thuế người bán"),
    description: str = typer.Option("Hàng hóa/Dịch vụ", "--desc", help="Mô tả hàng hóa"),
) -> None:
    """Tạo hóa đơn đơn giản và in summary."""
    invoice = create_invoice(
        amount=amount,
        vat_rate=vat_rate,
        buyer=buyer,
        seller=seller,
        seller_tax_code=seller_tax_code,
        description=description,
    )
    typer.echo(invoice.to_summary())


@ke_toan_app.command(name="xml")
def ke_toan_xml(
    amount: int = typer.Argument(..., help="Số tiền trước thuế (VND)"),
    vat_rate: int = typer.Option(10, "--vat", help="Thuế suất GTGT (0/5/8/10)"),
    buyer: str = typer.Option(..., "--buyer", help="Tên người mua"),
    seller: str = typer.Option("Doanh Nghiệp", "--seller", help="Tên người bán"),
    seller_tax_code: str = typer.Option("0000000000", "--mst", help="Mã số thuế người bán"),
    description: str = typer.Option("Hàng hóa/Dịch vụ", "--desc", help="Mô tả hàng hóa"),
) -> None:
    """Xuất XML hóa đơn theo schema TT78/2021."""
    invoice = create_invoice(
        amount=amount,
        vat_rate=vat_rate,
        buyer=buyer,
        seller=seller,
        seller_tax_code=seller_tax_code,
        description=description,
    )
    typer.echo(invoice.to_xml())


@ke_toan_app.command(name="journal")
def ke_toan_journal(
    amount: int = typer.Argument(..., help="Số tiền trước thuế (VND)"),
    vat_rate: int = typer.Option(10, "--vat", help="Thuế suất GTGT (0/5/8/10)"),
    buyer: str = typer.Option(..., "--buyer", help="Tên người mua"),
    seller: str = typer.Option("Doanh Nghiệp", "--seller", help="Tên người bán"),
    seller_tax_code: str = typer.Option("0000000000", "--mst", help="Mã số thuế người bán"),
    description: str = typer.Option("Hàng hóa/Dịch vụ", "--desc", help="Mô tả hàng hóa"),
) -> None:
    """Xuất bút toán kế toán VAS (JSON)."""
    invoice = create_invoice(
        amount=amount,
        vat_rate=vat_rate,
        buyer=buyer,
        seller=seller,
        seller_tax_code=seller_tax_code,
        description=description,
    )
    typer.echo(json.dumps(invoice.to_journal_entry(), ensure_ascii=False, indent=2))


@ke_toan_app.command(name="summary")
def ke_toan_summary(
    amount: int = typer.Argument(..., help="Số tiền trước thuế (VND)"),
    vat_rate: int = typer.Option(10, "--vat", help="Thuế suất GTGT (0/5/8/10)"),
    buyer: str = typer.Option(..., "--buyer", help="Tên người mua"),
    seller: str = typer.Option("Doanh Nghiệp", "--seller", help="Tên người bán"),
    seller_tax_code: str = typer.Option("0000000000", "--mst", help="Mã số thuế người bán"),
    description: str = typer.Option("Hàng hóa/Dịch vụ", "--desc", help="Mô tả hàng hóa"),
) -> None:
    """In summary hóa đơn (dạng text dễ đọc)."""
    invoice = create_invoice(
        amount=amount,
        vat_rate=vat_rate,
        buyer=buyer,
        seller=seller,
        seller_tax_code=seller_tax_code,
        description=description,
    )
    typer.echo(invoice.to_summary())
