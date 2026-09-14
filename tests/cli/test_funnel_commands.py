"""Tests for Vietnam funnel commands — Zalo OA, Thuế, Kế toán.

Covers:
- All three sub-apps registered in build_app()
- Offline commands produce expected output (thue tncn/tndn/gtgt, ke-toan create/xml/journal/summary, zalo-oa caption)
- zalo-oa send without token exits 1
- Help output for each sub-app

Part of gap #10 closure: reconnects the three business funnels to the binary.
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from src.cli.app_setup import build_app
from src.cli.funnel_commands import ke_toan_app, thue_app, zalo_app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestFunnelRegistration:
    """All three funnel sub-apps are wired into the root app."""

    def test_three_groups_registered(self) -> None:
        app = build_app()
        names = {g.name for g in app.registered_groups}
        assert "zalo-oa" in names
        assert "thue" in names
        assert "ke-toan" in names

    def test_total_group_count(self) -> None:
        """39 groups after funnel restoration (36 + 3)."""
        app = build_app()
        assert len(app.registered_groups) == 39


# ---------------------------------------------------------------------------
# Thuế VN
# ---------------------------------------------------------------------------


class TestThueCommands:
    """Offline tax calculations — no API, no token."""

    def test_tncn_basic(self) -> None:
        result = runner.invoke(thue_app, ["tncn", "30000000", "--dependents", "1"])
        assert result.exit_code == 0
        assert "TNCN" in result.output
        assert "30.000.000" in result.output

    def test_tncn_no_dependents(self) -> None:
        result = runner.invoke(thue_app, ["tncn", "20000000"])
        assert result.exit_code == 0
        assert "TNCN" in result.output

    def test_tndn_standard_rate(self) -> None:
        """Revenue above 3B threshold → 20% rate."""
        result = runner.invoke(thue_app, ["tndn", "5000000000"])
        assert result.exit_code == 0
        assert "TNDN" in result.output

    def test_tndn_sme_rate(self) -> None:
        """Revenue ≤ 3B → 17% SME rate."""
        result = runner.invoke(thue_app, ["tndn", "2000000000"])
        assert result.exit_code == 0
        assert "TNDN" in result.output

    def test_gtgt_default_rate(self) -> None:
        result = runner.invoke(thue_app, ["gtgt", "10000000"])
        assert result.exit_code == 0
        assert "GTGT" in result.output
        assert "10%" in result.output

    def test_gtgt_custom_rate(self) -> None:
        result = runner.invoke(thue_app, ["gtgt", "10000000", "--rate", "8"])
        assert result.exit_code == 0
        assert "8%" in result.output


# ---------------------------------------------------------------------------
# Kế toán VN
# ---------------------------------------------------------------------------


class TestKeToanCommands:
    """Offline invoice generation — no API, no token."""

    def test_create_summary(self) -> None:
        result = runner.invoke(
            ke_toan_app,
            ["create", "5000000", "--vat", "10", "--buyer", "Nguyễn Văn A"],
        )
        assert result.exit_code == 0
        assert "5.000.000" in result.output

    def test_xml_tt78(self) -> None:
        result = runner.invoke(
            ke_toan_app,
            ["xml", "5000000", "--vat", "10", "--buyer", "Test Co"],
        )
        assert result.exit_code == 0
        # TT78/2021 XML should contain key tags
        assert "HDon" in result.output or "DLHDon" in result.output or "invoice" in result.output.lower()

    def test_journal_vas(self) -> None:
        result = runner.invoke(
            ke_toan_app,
            ["journal", "5000000", "--vat", "10", "--buyer", "Test Co"],
        )
        assert result.exit_code == 0
        # VAS journal entry should reference account codes
        assert "131" in result.output or "511" in result.output or "3331" in result.output

    def test_summary_text(self) -> None:
        result = runner.invoke(
            ke_toan_app,
            ["summary", "5000000", "--vat", "10", "--buyer", "Test Co"],
        )
        assert result.exit_code == 0
        assert "5.000.000" in result.output


# ---------------------------------------------------------------------------
# Zalo OA
# ---------------------------------------------------------------------------


class TestZaloOaCommands:
    """Caption works offline; send/broadcast/followers/post require token."""

    def test_caption_offline(self) -> None:
        result = runner.invoke(zalo_app, ["caption", "bánh mì", "--tone", "vui_ve"])
        assert result.exit_code == 0
        assert "bánh mì" in result.output

    def test_caption_default_tone(self) -> None:
        result = runner.invoke(zalo_app, ["caption", "phở"])
        assert result.exit_code == 0
        assert "phở" in result.output

    def test_send_no_token_exits_1(self) -> None:
        """Without ZALO_OA_ACCESS_TOKEN, send must exit 1."""
        with patch.dict("os.environ", {}, clear=True):
            result = runner.invoke(zalo_app, ["send", "user_1", "hello"])
            assert result.exit_code == 1

    def test_broadcast_no_token_exits_1(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = runner.invoke(zalo_app, ["broadcast", "hello"])
            assert result.exit_code == 1

    def test_followers_no_token_exits_1(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = runner.invoke(zalo_app, ["followers"])
            assert result.exit_code == 1

    def test_post_no_token_exits_1(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = runner.invoke(zalo_app, ["post", "Title", "Content"])
            assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Help output
# ---------------------------------------------------------------------------


class TestHelpOutput:
    """Each sub-app renders help correctly."""

    def test_thue_help(self) -> None:
        result = runner.invoke(thue_app, ["--help"])
        assert result.exit_code == 0
        assert "tncn" in result.output
        assert "tndn" in result.output
        assert "gtgt" in result.output

    def test_ke_toan_help(self) -> None:
        result = runner.invoke(ke_toan_app, ["--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "xml" in result.output
        assert "journal" in result.output
        assert "summary" in result.output

    def test_zalo_help(self) -> None:
        result = runner.invoke(zalo_app, ["--help"])
        assert result.exit_code == 0
        assert "send" in result.output
        assert "broadcast" in result.output
        assert "followers" in result.output
        assert "caption" in result.output
        assert "post" in result.output

    def test_root_help_shows_funnel_groups(self) -> None:
        """The root app help lists the three new funnel groups."""
        app = build_app()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "zalo-oa" in result.output
        assert "thue" in result.output
        assert "ke-toan" in result.output
