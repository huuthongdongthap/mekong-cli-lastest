"""Tests for the Core DNA GitHub Actions gate."""

from __future__ import annotations

from pathlib import Path

import yaml


WORKFLOW_PATH = Path(".github/workflows/core-dna-gate.yml")


def test_core_dna_workflow_runs_harness_eval() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["core-dna-gate"]["steps"]
    commands = "\n".join(str(step.get("run", "")) for step in steps)

    assert "python3 -m pip install -e ." in commands
    assert "run_solo_ceo_harness_evals" in commands


def test_core_dna_workflow_watches_doctrine_manifest() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "binh-phap-operating-system" in text
    assert "owner/community review" in text
