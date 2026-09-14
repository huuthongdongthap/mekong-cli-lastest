# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Surface tests for the built Typer app.

Asserts that the billing, pev, and usage command groups are registered
on the root app produced by build_app(). Real behavior only — no mocks.
"""

from __future__ import annotations

from src.cli.app_setup import build_app


def _registered_group_names() -> list[str]:
    app = build_app()
    return [group.name for group in app.registered_groups]


def test_billing_group_registered() -> None:
    assert "billing" in _registered_group_names()


def test_pev_group_registered() -> None:
    assert "pev" in _registered_group_names()


def test_usage_group_registered() -> None:
    assert "usage" in _registered_group_names()
