# Mekong CLI — MIT License. Copyright (c) 2026 MekongMind.

"""Tests for dna.py — parse / load / merge / export. Real validation, no mocks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.design_intelligence.dna import export_dna, load_dna, merge_dna, parse_dna
from src.design_intelligence.schemas import DesignDNA, ProductType

from tests.design_intelligence.test_schemas import landing_page_dna, trading_dashboard_dna


class TestParseDna:
    def test_parse_valid_payload(self) -> None:
        dna = parse_dna(landing_page_dna())
        assert isinstance(dna, DesignDNA)
        assert dna.product_type is ProductType.LANDING_PAGE

    def test_parse_invalid_payload_raises_value_error(self) -> None:
        data = landing_page_dna()
        data["confidence"] = 2.0
        with pytest.raises(ValueError, match="invalid DesignDNA payload"):
            parse_dna(data)

    def test_parse_non_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            parse_dna(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_parse_error_message_names_field(self) -> None:
        data = trading_dashboard_dna()
        data["product_type"] = "not-a-real-type"
        with pytest.raises(ValueError, match="product_type"):
            parse_dna(data)


class TestLoadDna:
    def test_load_json_file(self, tmp_path: Path) -> None:
        path = tmp_path / "dna.json"
        path.write_text(json.dumps(landing_page_dna()), encoding="utf-8")
        dna = load_dna(path)
        assert dna.audience == "Urban Vietnamese consumers aged 25-40"

    def test_load_yaml_file(self, tmp_path: Path) -> None:
        yaml = pytest.importorskip("yaml")
        path = tmp_path / "dna.yaml"
        path.write_text(yaml.safe_dump(trading_dashboard_dna()), encoding="utf-8")
        dna = load_dna(path)
        assert dna.product_type is ProductType.TRADING_TERMINAL

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="DNA file not found"):
            load_dna(tmp_path / "nope.json")

    def test_load_non_object_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "dna.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ValueError, match="must contain a JSON/YAML object"):
            load_dna(path)

    def test_load_invalid_schema_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "dna.json"
        path.write_text(json.dumps({"identity": "x"}), encoding="utf-8")
        with pytest.raises(ValueError, match="invalid DesignDNA payload"):
            load_dna(path)


class TestMergeDna:
    def test_override_wins(self) -> None:
        base = parse_dna(landing_page_dna())
        merged = merge_dna(base, {"audience": "Gen Z coffee lovers"})
        assert merged.audience == "Gen Z coffee lovers"
        # Untouched axes keep base values.
        assert merged.identity == base.identity
        assert merged.confidence == base.confidence

    def test_none_does_not_overwrite(self) -> None:
        base = parse_dna(landing_page_dna())
        merged = merge_dna(base, {"audience": None, "color_anchor": None})
        assert merged.audience == base.audience
        assert merged.color_anchor == base.color_anchor

    def test_empty_containers_do_not_overwrite(self) -> None:
        base = parse_dna(landing_page_dna())
        merged = merge_dna(
            base,
            {"brand_character": [], "type_pairing": {}, "identity": ""},
        )
        assert merged.brand_character == base.brand_character
        assert merged.type_pairing == base.type_pairing
        assert merged.identity == base.identity

    def test_merge_can_introduce_new_values(self) -> None:
        base = parse_dna(landing_page_dna())
        assert base.macrostructure is not None
        merged = merge_dna(base, {"macrostructure": "Hero -> pricing -> FAQ"})
        assert merged.macrostructure == "Hero -> pricing -> FAQ"

    def test_merge_unknown_key_raises(self) -> None:
        base = parse_dna(landing_page_dna())
        with pytest.raises(ValueError, match="invalid DesignDNA payload"):
            merge_dna(base, {"mystery_axis": True})

    def test_merge_non_dict_raises(self) -> None:
        base = parse_dna(landing_page_dna())
        with pytest.raises(ValueError, match="override must be a dict"):
            merge_dna(base, "audience=x")  # type: ignore[arg-type]


class TestExportDna:
    def test_export_is_json_serializable(self) -> None:
        dna = parse_dna(trading_dashboard_dna())
        exported = export_dna(dna)
        round_tripped = json.loads(json.dumps(exported))
        assert round_tripped["product_type"] == "trading-terminal"
        assert round_tripped["density"] == "dense"

    def test_export_round_trips_through_parse(self) -> None:
        dna = parse_dna(landing_page_dna())
        assert parse_dna(export_dna(dna)) == dna
