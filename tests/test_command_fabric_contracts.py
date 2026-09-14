import json

from src.command_fabric.catalog import build_command_catalog
from src.command_fabric.contracts import (
    contract_coverage,
    generated_contract,
    materialize_command_contracts,
)


def test_generated_contract_has_deep_command_metadata() -> None:
    cook = next(record for record in build_command_catalog() if record.name == "cook")
    contract = generated_contract(cook)

    assert contract["schema"] == "mekong.command_contract.v1"
    assert contract["id"] == "cook"
    assert contract["source"] == ".claude/commands/cook.md"
    assert contract["execution"]["command"].startswith("python3 -m src.main cook")
    assert "vscode" in contract["execution"]["portability_targets"]
    assert contract["input"]["properties"]["arguments"]["type"] == "string"
    assert contract["output"]["required"] == ["exit_code"]


def test_contract_coverage_is_complete_with_generated_contracts() -> None:
    records = build_command_catalog()
    coverage = contract_coverage(records)

    assert coverage.command_count == len(records)
    assert coverage.existing_contract_count >= 1
    assert coverage.generated_contract_count == len(records) - coverage.existing_contract_count
    assert coverage.complete is True
    assert coverage.missing_contracts == []


def test_materialize_command_contracts_writes_one_contract_per_command(tmp_path) -> None:
    records = build_command_catalog()
    payload = materialize_command_contracts(tmp_path, records)
    cook_path = tmp_path / "contracts" / "commands" / "cook.json"

    assert payload["schema"] == "mekong.command_contracts.materialized.v1"
    assert payload["contract_count"] == len(records)
    assert payload["coverage"]["complete"] is True
    assert cook_path.exists()
    assert json.loads(cook_path.read_text(encoding="utf-8"))["id"] == "cook"


def test_command_fabric_materializes_contracts_default(tmp_path) -> None:
    payload = materialize_command_contracts(tmp_path)

    assert payload["contract_count"] == len(build_command_catalog())
    assert payload["coverage"]["complete"] is True
    assert (tmp_path / "contracts" / "commands" / "ask.json").exists()

