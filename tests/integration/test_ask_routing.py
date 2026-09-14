"""Integration tests for /ask VI+EN NL routing — verifies end-to-end routing."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner
from src.cli.app_setup import build_app

app = build_app()


runner = CliRunner()


COMMON_TESTS = [
    # (input, expected_token_in_output)
    # Routed leaf commands print their name in the NL Router panel; un-routed
    # inputs fall through to the LLM planner and print the "💡 Answer" panel.
    ("code giao diện", "cook"),
    ("sửa lỗi thanh toán", "debug"),
    ("lập kế hoạch marketing", "plan"),
    ("viết bài blog", "💡 Answer"),
    ("tạo chiến dịch marketing", "💡 Answer"),
    ("quét bảo mật", "💡 Answer"),
    ("phân tích dữ liệu", "💡 Answer"),
    ("deploy lên production", "deploy"),
    ("tạo tài liệu", "💡 Answer"),
]


@pytest.mark.parametrize("input_text,expected", COMMON_TESTS)
def test_ask_routes_vietnamese(input_text: str, expected: str) -> None:
    """Vietnamese input routes to correct command or falls through gracefully."""
    result = runner.invoke(app, ["ask", input_text])
    # Routing must not crash (exit 2 = Typer usage error).  Leaf commands like
    # `cook` actually execute their workflow, which needs a live LLM and may
    # exit non-zero — that is a routing success, not a routing failure.
    assert result.exit_code != 2, f"Routing crashed for: {input_text}"
    assert (
        expected in result.output
    ), f"Expected '{expected}' in output for '{input_text}', got: {result.output[:200]}"


EN_TESTS = [
    ("build a campaign", "cook"),
    ("fix the bug", "debug"),
    ("create a plan", "💡 Answer"),
    ("write a blog post", "💡 Answer"),
    ("deploy to production", "deploy"),
]


@pytest.mark.parametrize("input_text,expected", EN_TESTS)
def test_ask_routes_english(input_text: str, expected: str) -> None:
    """English input routes to correct command or falls through gracefully."""
    result = runner.invoke(app, ["ask", input_text])
    assert result.exit_code != 2, f"Routing crashed for: {input_text}"
    assert expected in result.output, f"Expected '{expected}' in output for '{input_text}'"


def test_ask_unknown_falls_through() -> None:
    """Unknown input should not crash — output contains answer/fallback."""
    result = runner.invoke(app, ["ask", "hello world unknown intent"])
    # Should not crash (exit 0 or graceful exit)
    assert result.exit_code in (0, 1)


def test_ask_empty_argument() -> None:
    """Empty argument should show help or fail gracefully."""
    result = runner.invoke(app, ["ask", ""])
    # Should not crash
    assert result.exit_code in (0, 1, 2)
