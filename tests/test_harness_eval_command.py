# Mekong CLI — AI-Powered Business Operations for Vietnam
# MIT License. Copyright (c) 2026 MekongMind. See LICENSE file.

"""Tests for the root-level ``harness-eval`` command."""

from __future__ import annotations

import json

import typer
from typer.testing import CliRunner

from src.cli.app_setup import build_app
from src.cli.commands.harness_eval_command import register_harness_eval_command


def test_harness_eval_command_registered_on_root() -> None:
    """The harness-eval command is wired onto the root Typer app."""
    app = build_app()
    assert "harness-eval" in app.registered_commands or any(
        cmd.name == "harness-eval" for cmd in app.registered_commands
    )


def test_harness_eval_command_runs_and_exits_zero() -> None:
    """Plain invocation prints results and exits 0 when all evals pass."""
    runner = CliRunner()
    result = runner.invoke(build_app(), ["harness-eval"])

    assert result.exit_code == 0
    assert "EVAL-07" in result.output
    assert "6/6" in result.output


def test_harness_eval_json_flag_parses_and_exits_zero() -> None:
    """``--json`` emits a parseable JSON payload and exits 0."""
    runner = CliRunner()
    result = runner.invoke(build_app(), ["harness-eval", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["suite"] == "solo-ceo-harness"
    assert payload["passed"] is True
    assert payload["total"] == 6
    assert payload["passed_count"] == 6
    assert {r["id"] for r in payload["results"]} == {
        "EVAL-07",
        "EVAL-08",
        "EVAL-09",
        "EVAL-10",
        "EVAL-11",
        "EVAL-12",
    }


def test_harness_eval_exit_code_is_one_on_failure() -> None:
    """Exit code is 1 when any eval fails, via a manifest that breaks one check."""
    import pytest

    with pytest.MonkeyPatch.context() as monkey:
        monkey.setattr(
            "src.harness.evals.solo_ceo.eval_core_dna_attestation",
            lambda: __import__(
                "src.harness.evals.solo_ceo", fromlist=["HarnessEvalResult"]
            ).HarnessEvalResult(
                id="EVAL-09",
                name="Core DNA Attestation",
                passed=False,
                evidence={},
                failure="broken",
            ),
        )
        app = typer.Typer()
        register_harness_eval_command(app)
        runner = CliRunner()
        result = runner.invoke(app, ["--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert payload["passed_count"] == 5


def test_harness_eval_evals_pass_6_of_6() -> None:
    """The underlying eval suite passes all six checks."""
    from src.harness.evals.solo_ceo import run_solo_ceo_harness_evals

    payload = run_solo_ceo_harness_evals()
    assert payload["passed"] is True
    assert payload["total"] == 6
    assert payload["passed_count"] == 6