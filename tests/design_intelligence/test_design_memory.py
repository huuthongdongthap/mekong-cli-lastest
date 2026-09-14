# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Tests for design memory + the Sophia interface (study --export-json, approve)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli.app_setup import build_app
from src.cli.ui_study import STUDIES_DIR, _deterministic_dna
from src.design_intelligence.design_memory import (
    approve_design,
    list_approved,
    list_rejected,
    load_approved,
    reject_pattern,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "tests" / "design_intelligence" / "fixtures"
GOOD = (FIXTURES / "good-dashboard.html").read_text()


# ------------------------------------------------------------------ design memory
def test_approve_then_load_approved_round_trip(tmp_path: Path) -> None:
    store = tmp_path / "memory.jsonl"
    dna = _deterministic_dna(GOOD, "file:good")
    approve_design("good-dashboard", dna, audit_summary="signed off", path=store)
    loaded = load_approved("good-dashboard", path=store)
    assert loaded is not None
    assert loaded.product_type.value == dna.product_type.value
    assert loaded.identity == dna.identity


def test_unapproved_study_is_not_in_memory(tmp_path: Path) -> None:
    """Memory only ever holds approved DNA — never study output on disk."""
    store = tmp_path / "memory.jsonl"
    assert load_approved("never-approved", path=store) is None
    assert list_approved(path=store) == []


def test_reject_pattern_records_and_lists(tmp_path: Path) -> None:
    store = tmp_path / "memory.jsonl"
    reject_pattern("slop-landing", "too many gradients", path=store)
    assert list_rejected(path=store) == ["slop-landing"]
    assert list_approved(path=store) == []


def test_rejected_pattern_is_not_loadable_as_dna(tmp_path: Path) -> None:
    store = tmp_path / "memory.jsonl"
    reject_pattern("slop-landing", "nope", path=store)
    assert load_approved("slop-landing", path=store) is None


def test_list_approved_deduplicates(tmp_path: Path) -> None:
    store = tmp_path / "memory.jsonl"
    dna = _deterministic_dna(GOOD, "file:good")
    approve_design("good-dashboard", dna, path=store)
    approve_design("good-dashboard", dna, path=store)  # idempotent re-approve
    assert list_approved(path=store) == ["good-dashboard"]


def test_corrupt_memory_entry_does_not_crash(tmp_path: Path) -> None:
    store = tmp_path / "memory.jsonl"
    store.write_text("{not valid json\n", encoding="utf-8")
    assert load_approved("x", path=store) is None
    assert list_approved(path=store) == []


# ------------------------------------------------------------------ study --export-json
def test_study_export_json_emits_trailing_dna(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    res = runner.invoke(
        build_app(),
        ["ui", "study", str(FIXTURES / "good-dashboard.html"), "--name", "g", "--export-json"],
    )
    assert res.exit_code == 0
    payload = json.loads(res.output[res.output.rindex("\n{"):])
    assert payload["product_type"] == "saas-dashboard"
    assert "identity" in payload
    assert "confidence" in payload


def test_study_writes_files_without_export_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    res = runner.invoke(
        build_app(),
        ["ui", "study", str(FIXTURES / "good-dashboard.html"), "--name", "g"],
    )
    assert res.exit_code == 0
    assert (tmp_path / STUDIES_DIR / "g" / "design.json").exists()
    assert (tmp_path / STUDIES_DIR / "g" / "design.md").exists()
    assert "{" not in res.output  # no JSON leaked to stdout


# ------------------------------------------------------------------ approve command
def test_approve_command_stores_in_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(
        build_app(),
        ["ui", "study", str(FIXTURES / "good-dashboard.html"), "--name", "g"],
    )
    res = runner.invoke(build_app(), ["ui", "approve", "g"])
    assert res.exit_code == 0
    # approve_cmd writes to the default store (.mekong/memory.jsonl under CWD)
    assert load_approved("g", path=tmp_path / ".mekong" / "memory.jsonl") is not None


def test_approve_unknown_study_exits_nonzero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    res = runner.invoke(build_app(), ["ui", "approve", "nope"])
    assert res.exit_code != 0


def test_reject_command_records_pattern(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(
        build_app(),
        ["ui", "study", str(FIXTURES / "slop-landing.html"), "--name", "s"],
    )
    res = runner.invoke(
        build_app(), ["ui", "approve", "s", "--reject", "--reason", "too many gradients"]
    )
    assert res.exit_code == 0
    # approve_cmd writes to the default store (.mekong/memory.jsonl under CWD)
    store = tmp_path / ".mekong" / "memory.jsonl"
    assert list_rejected(path=store) == ["s"]
    assert load_approved("s", path=store) is None