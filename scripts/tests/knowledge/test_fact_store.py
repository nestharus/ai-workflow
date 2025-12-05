"""Tests for scripts.knowledge.fact_store module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.knowledge.compare_yaml_docs import ContainmentEdge, FieldFact
from scripts.knowledge.fact_store import (
    FactStoreRecord,
    containment_edges_to_edge_records,
    decorate_yaml_main,
    decorate_yaml_with_entity_id,
    decorate_yaml_with_fact_ids,
    determine_primary_domain,
    ensure_fact_yaml_exists,
    entity_ref_fieldfacts_to_edge_records,
    export_facts_to_jsonl,
    fieldfact_to_structural_record,
    get_entity_id_from_variants,
    get_fact_by_id,
    list_fact_files,
    organize_facts_by_domain_pattern,
    parse_decorate_args,
    parse_export_jsonl_args,
    parse_query_args,
    parse_store_args,
    parse_store_structural_args,
    query_facts_from_yaml,
    query_facts_main,
    query_structural_facts,
    read_facts_from_csv,
    store_fact_main,
    store_fact_to_yaml,
    store_structural_facts,
)


class TestEnsureFactYamlExists:
    """Tests for ensure_fact_yaml_exists function."""

    def test_creates_yaml_with_schema_if_missing(self, tmp_path: Path) -> None:
        """Should create YAML file with empty facts list if missing."""
        yaml_path = tmp_path / "facts" / "test.facts.yml"

        ensure_fact_yaml_exists(yaml_path)

        assert yaml_path.exists()
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data == {"facts": []}

    def test_does_not_overwrite_existing_yaml(self, tmp_path: Path) -> None:
        """Should not overwrite existing YAML file."""
        yaml_path = tmp_path / "test.facts.yml"
        existing_content = {"facts": [{"fact_id": "existing"}]}
        yaml_path.write_text(yaml.dump(existing_content))

        ensure_fact_yaml_exists(yaml_path)

        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert len(data["facts"]) == 1
        assert data["facts"][0]["fact_id"] == "existing"


class TestStoreFactToYaml:
    """Tests for store_fact_to_yaml function."""

    def test_appends_fact_to_new_yaml(self, tmp_path: Path) -> None:
        """Should create YAML and append fact."""
        yaml_path = tmp_path / "test.facts.yml"
        record = FactStoreRecord(
            fact_id="uuid-1",
            entity="create_app",
            fact_text="create_app is located in app/core/factory.py",
            source_file="docs/test.yml",
            source_element_id="elem-1",
            confidence=0.95,
            extracted_at="2024-01-01T00:00:00Z",
            domain="fastapi",
            pattern="factory",
        )

        result = store_fact_to_yaml(yaml_path, record)

        assert result == 1
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert len(data["facts"]) == 1
        assert data["facts"][0]["fact_id"] == "uuid-1"

    def test_appends_fact_to_existing_yaml(self, tmp_path: Path) -> None:
        """Should append fact to existing YAML file."""
        yaml_path = tmp_path / "test.facts.yml"
        existing = {"facts": [{"fact_id": "existing"}]}
        yaml_path.write_text(yaml.dump(existing))

        record = FactStoreRecord(
            fact_id="uuid-2",
            entity="FastAPI",
            fact_text="FastAPI is a web framework",
            source_file="docs/test.yml",
            source_element_id="elem-2",
            confidence=0.9,
            extracted_at="2024-01-02T00:00:00Z",
            domain="rest",
            pattern="api",
        )

        result = store_fact_to_yaml(yaml_path, record)

        assert result == 1
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert len(data["facts"]) == 2

    def test_preserves_existing_facts(self, tmp_path: Path) -> None:
        """Should not lose existing facts when appending."""
        yaml_path = tmp_path / "test.facts.yml"
        existing = {"facts": [{"fact_id": "keep-me", "fact_text": "original fact"}]}
        yaml_path.write_text(yaml.dump(existing))

        record = FactStoreRecord(
            fact_id="new-fact",
            entity="test",
            fact_text="new fact",
            source_file="",
            source_element_id="",
            confidence=0.8,
            extracted_at="2024-01-01",
            domain="test",
            pattern="test",
        )

        store_fact_to_yaml(yaml_path, record)

        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        fact_ids = [f["fact_id"] for f in data["facts"]]
        assert "keep-me" in fact_ids
        assert "new-fact" in fact_ids

    def test_does_not_duplicate_fact_ids(self, tmp_path: Path) -> None:
        """Should not duplicate facts with same ID."""
        yaml_path = tmp_path / "test.facts.yml"
        record = FactStoreRecord(
            fact_id="duplicate-id",
            entity="test",
            fact_text="fact",
            source_file="",
            source_element_id="",
            confidence=0.8,
            extracted_at="2024-01-01",
            domain="test",
            pattern="test",
        )

        store_fact_to_yaml(yaml_path, record)
        store_fact_to_yaml(yaml_path, record)  # Add again

        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert len(data["facts"]) == 1


class TestReadFactsFromCsv:
    """Tests for read_facts_from_csv function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty list when CSV doesn't exist."""
        csv_path = tmp_path / "extractions.csv"
        result = read_facts_from_csv(csv_path)
        assert result == []

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV."""
        csv_path = tmp_path / "extractions.csv"
        csv_path.write_text("")
        result = read_facts_from_csv(csv_path)
        assert result == []

    def test_filters_by_entity(self, tmp_path: Path) -> None:
        """Should filter facts by entity when provided."""
        csv_path = tmp_path / "extractions.csv"
        csv_path.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,iteration,confidence,extracted_at\n"
            "id-1,sent1,create_app,fact1,residual1,1,0.9,2024-01-01\n"
            "id-2,sent2,FastAPI,fact2,residual2,1,0.8,2024-01-01\n"
        )

        result = read_facts_from_csv(csv_path, entity="create_app")

        assert len(result) == 1
        assert result[0]["entity"] == "create_app"

    def test_returns_all_facts_when_no_filter(self, tmp_path: Path) -> None:
        """Should return all facts when no entity filter."""
        csv_path = tmp_path / "extractions.csv"
        csv_path.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,iteration,confidence,extracted_at\n"
            "id-1,sent1,entity1,fact1,residual1,1,0.9,2024-01-01\n"
            "id-2,sent2,entity2,fact2,residual2,1,0.8,2024-01-01\n"
        )

        result = read_facts_from_csv(csv_path)

        assert len(result) == 2


class TestOrganizeFactsByDomainPattern:
    """Tests for organize_facts_by_domain_pattern function."""

    def test_converts_facts_to_store_records(self) -> None:
        """Should convert extraction facts to store records with float confidence."""
        facts = [
            {
                "fact_id": "id-1",
                "entity": "create_app",
                "fact_text": "fact about create_app",
                "confidence": "0.9",
                "extracted_at": "2024-01-01",
            }
        ]

        records = organize_facts_by_domain_pattern(
            facts,
            domain="fastapi",
            pattern="factory",
            source_file="docs/test.yml",
            source_element_id="elem-1",
        )

        assert len(records) == 1
        assert records[0]["domain"] == "fastapi"
        assert records[0]["pattern"] == "factory"
        assert records[0]["source_file"] == "docs/test.yml"
        assert records[0]["confidence"] == 0.9  # Should be float, not string
        assert isinstance(records[0]["confidence"], float)

    def test_handles_empty_confidence(self) -> None:
        """Should default to 0.0 for empty or missing confidence."""
        facts = [
            {
                "fact_id": "id-1",
                "entity": "test",
                "fact_text": "fact",
                "confidence": "",
                "extracted_at": "2024-01-01",
            }
        ]

        records = organize_facts_by_domain_pattern(facts, domain="d", pattern="p")

        assert records[0]["confidence"] == 0.0

    def test_handles_invalid_confidence(self) -> None:
        """Should default to 0.0 for invalid confidence values."""
        facts = [
            {
                "fact_id": "id-1",
                "entity": "test",
                "fact_text": "fact",
                "confidence": "not-a-number",
                "extracted_at": "2024-01-01",
            }
        ]

        records = organize_facts_by_domain_pattern(facts, domain="d", pattern="p")

        assert records[0]["confidence"] == 0.0


class TestListFactFiles:
    """Tests for list_fact_files function."""

    def test_returns_empty_for_missing_directory(self, tmp_path: Path) -> None:
        """Should return empty list when directory doesn't exist."""
        facts_dir = tmp_path / "nonexistent"
        result = list_fact_files(facts_dir)
        assert result == []

    def test_returns_fact_files(self, tmp_path: Path) -> None:
        """Should return all .facts.yml files."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        (facts_dir / "fastapi.factory.facts.yml").write_text("facts: []")
        (facts_dir / "rest.api.facts.yml").write_text("facts: []")
        (facts_dir / "other.csv").write_text("")  # Should be ignored

        result = list_fact_files(facts_dir)

        assert len(result) == 2
        filenames = [f.name for f in result]
        assert "fastapi.factory.facts.yml" in filenames
        assert "rest.api.facts.yml" in filenames


class TestQueryFactsFromYaml:
    """Tests for query_facts_from_yaml function."""

    def test_returns_empty_for_missing_directory(self, tmp_path: Path) -> None:
        """Should return empty list when facts directory missing."""
        facts_dir = tmp_path / "nonexistent"
        result = query_facts_from_yaml(facts_dir)
        assert result == []

    def test_filters_by_domain(self, tmp_path: Path) -> None:
        """Should filter facts by domain."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        (facts_dir / "fastapi.factory.facts.yml").write_text(
            yaml.dump({"facts": [{"entity": "test", "domain": "fastapi"}]})
        )
        (facts_dir / "rest.api.facts.yml").write_text(
            yaml.dump({"facts": [{"entity": "test", "domain": "rest"}]})
        )

        result = query_facts_from_yaml(facts_dir, domain="fastapi")

        assert len(result) == 1
        assert result[0]["domain"] == "fastapi"

    def test_filters_by_pattern(self, tmp_path: Path) -> None:
        """Should filter facts by pattern."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        (facts_dir / "fastapi.factory.facts.yml").write_text(
            yaml.dump({"facts": [{"entity": "test", "pattern": "factory"}]})
        )
        (facts_dir / "fastapi.routes.facts.yml").write_text(
            yaml.dump({"facts": [{"entity": "test", "pattern": "routes"}]})
        )

        result = query_facts_from_yaml(facts_dir, pattern="factory")

        assert len(result) == 1
        assert result[0]["pattern"] == "factory"

    def test_filters_by_entity(self, tmp_path: Path) -> None:
        """Should filter facts by entity within files."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        (facts_dir / "fastapi.factory.facts.yml").write_text(
            yaml.dump(
                {
                    "facts": [
                        {"entity": "create_app"},
                        {"entity": "other"},
                    ]
                }
            )
        )

        result = query_facts_from_yaml(facts_dir, entity="create_app")

        assert len(result) == 1
        assert result[0]["entity"] == "create_app"

    def test_returns_all_facts_when_no_filter(self, tmp_path: Path) -> None:
        """Should return all facts when no filters provided."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        (facts_dir / "fastapi.factory.facts.yml").write_text(
            yaml.dump({"facts": [{"entity": "e1"}, {"entity": "e2"}]})
        )

        result = query_facts_from_yaml(facts_dir)

        assert len(result) == 2


class TestGetFactById:
    """Tests for get_fact_by_id function."""

    def test_returns_none_for_missing_fact(self, tmp_path: Path) -> None:
        """Should return None when fact not found."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        (facts_dir / "test.domain.facts.yml").write_text(
            yaml.dump({"facts": [{"fact_id": "other-id"}]})
        )

        result = get_fact_by_id(facts_dir, "nonexistent-id")

        assert result is None

    def test_returns_fact_for_valid_id(self, tmp_path: Path) -> None:
        """Should return fact when ID found."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        (facts_dir / "test.domain.facts.yml").write_text(
            yaml.dump({"facts": [{"fact_id": "target-id", "fact_text": "found"}]})
        )

        result = get_fact_by_id(facts_dir, "target-id")

        assert result is not None
        assert result["fact_text"] == "found"


class TestGetEntityIdFromVariants:
    """Tests for get_entity_id_from_variants function."""

    def test_returns_none_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return None when variants CSV missing."""
        csv_path = tmp_path / "variants.csv"
        result = get_entity_id_from_variants(csv_path, "entity")
        assert result is None

    def test_returns_none_for_no_match(self, tmp_path: Path) -> None:
        """Should return None when entity not found."""
        csv_path = tmp_path / "variants.csv"
        csv_path.write_text(
            "pair_id,keyword_a,keyword_b,similarity,merge,canonical,reason,validated\n"
            "id-1,other,another,0.9,true,other,reason,true\n"
        )

        result = get_entity_id_from_variants(csv_path, "nonexistent")

        assert result is None

    def test_returns_entity_id_for_canonical(self, tmp_path: Path) -> None:
        """Should return pair_id when entity matches keyword_a."""
        csv_path = tmp_path / "variants.csv"
        csv_path.write_text(
            "pair_id,keyword_a,keyword_b,similarity,merge,canonical,reason,validated\n"
            "found-id,create_app,createApp,0.95,true,create_app,merged,true\n"
        )

        result = get_entity_id_from_variants(csv_path, "create_app")

        assert result == "found-id"

    def test_returns_entity_id_for_variant(self, tmp_path: Path) -> None:
        """Should return pair_id when entity matches keyword_b."""
        csv_path = tmp_path / "variants.csv"
        csv_path.write_text(
            "pair_id,keyword_a,keyword_b,similarity,merge,canonical,reason,validated\n"
            "found-id,create_app,createApp,0.95,true,create_app,merged,true\n"
        )

        result = get_entity_id_from_variants(csv_path, "createApp")

        assert result == "found-id"

    def test_returns_none_for_unvalidated(self, tmp_path: Path) -> None:
        """Should return None when merge is not validated."""
        csv_path = tmp_path / "variants.csv"
        csv_path.write_text(
            "pair_id,keyword_a,keyword_b,similarity,merge,canonical,reason,validated\n"
            "id-1,create_app,createApp,0.95,true,create_app,pending,false\n"
        )

        result = get_entity_id_from_variants(csv_path, "create_app")

        assert result is None


class TestDecorateYamlWithFactIds:
    """Tests for decorate_yaml_with_fact_ids function."""

    def test_adds_fact_ids_to_element(self, tmp_path: Path) -> None:
        """Should add fact_ids list to element and return count of IDs added."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test item\n")

        result, updates = decorate_yaml_with_fact_ids(yaml_path, "elem-1", ["uuid-1", "uuid-2"])

        assert result == 2  # Returns count of new IDs added
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["items"][0]["fact_ids"] == ["uuid-1", "uuid-2"]
        assert any("added 2 fact ID(s)" in u for u in updates)

    def test_merges_with_existing_fact_ids(self, tmp_path: Path) -> None:
        """Should merge with existing fact_ids and return count of new IDs only."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text(
            "items:\n  - id: elem-1\n    text: Test\n    fact_ids:\n      - existing\n"
        )

        result, _updates = decorate_yaml_with_fact_ids(yaml_path, "elem-1", ["existing", "new"])

        assert result == 1  # Only "new" was added, "existing" was deduplicated
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        # Should have both, without duplicating "existing"
        assert "existing" in data["items"][0]["fact_ids"]
        assert "new" in data["items"][0]["fact_ids"]
        assert len(data["items"][0]["fact_ids"]) == 2

    def test_returns_zero_when_all_ids_exist(self, tmp_path: Path) -> None:
        """Should return 0 when all provided IDs already exist."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text(
            "items:\n  - id: elem-1\n    text: Test\n    fact_ids:\n      - existing\n"
        )

        result, updates = decorate_yaml_with_fact_ids(yaml_path, "elem-1", ["existing"])

        assert result == 0  # No new IDs added
        assert any("no new fact IDs to add" in u for u in updates)

    def test_returns_zero_for_missing_element(self, tmp_path: Path) -> None:
        """Should return 0 when element not found."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: other\n    text: Test\n")

        result, updates = decorate_yaml_with_fact_ids(yaml_path, "nonexistent", ["uuid-1"])

        assert result == 0
        assert any("not found" in u for u in updates)

    def test_returns_zero_for_parse_failure(self, tmp_path: Path) -> None:
        """Should return 0 when YAML parse fails."""
        yaml_path = tmp_path / "invalid.yml"
        yaml_path.write_text("invalid: yaml: [")

        result, updates = decorate_yaml_with_fact_ids(yaml_path, "elem-1", ["uuid-1"])

        assert result == 0
        assert updates == []

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        """Should not modify file in dry run mode but return count of IDs that would be added."""
        yaml_path = tmp_path / "test.yml"
        original = "items:\n  - id: elem-1\n    text: Test\n"
        yaml_path.write_text(original)

        result, _updates = decorate_yaml_with_fact_ids(
            yaml_path, "elem-1", ["uuid-1"], dry_run=True
        )

        assert result == 1  # Returns count of IDs that would be added
        assert yaml_path.read_text() == original


class TestDecorateYamlWithEntityId:
    """Tests for decorate_yaml_with_entity_id function."""

    def test_adds_entity_id_to_element(self, tmp_path: Path) -> None:
        """Should add entity_id to element."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test\n")

        result, _updates = decorate_yaml_with_entity_id(
            yaml_path, "elem-1", "create_app", "entity-uuid"
        )

        assert result == 1
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["items"][0]["entity_id"] == "entity-uuid"

    def test_overwrites_existing_entity_id(self, tmp_path: Path) -> None:
        """Should overwrite existing entity_id."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test\n    entity_id: old-id\n")

        result, _updates = decorate_yaml_with_entity_id(yaml_path, "elem-1", "create_app", "new-id")

        assert result == 1
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["items"][0]["entity_id"] == "new-id"

    def test_returns_zero_for_missing_element(self, tmp_path: Path) -> None:
        """Should return 0 when element not found."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: other\n    text: Test\n")

        result, updates = decorate_yaml_with_entity_id(yaml_path, "nonexistent", "entity", "uuid")

        assert result == 0
        assert any("not found" in u for u in updates)


class TestParseStoreArgs:
    """Tests for parse_store_args function."""

    def test_required_args(self) -> None:
        """Should require entity, domain, and pattern."""
        args = parse_store_args(
            ["--entity", "create_app", "--domain", "fastapi", "--pattern", "factory"]
        )
        assert args.entity == "create_app"
        assert args.domain == "fastapi"
        assert args.pattern == "factory"

    def test_default_knowledge_path(self) -> None:
        """Should use default knowledge path."""
        args = parse_store_args(["--entity", "e", "--domain", "d", "--pattern", "p"])
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_knowledge_path(self) -> None:
        """Should accept custom knowledge path."""
        args = parse_store_args(
            [
                "--entity",
                "e",
                "--domain",
                "d",
                "--pattern",
                "p",
                "--knowledge-path",
                "custom/.knowledge",
            ]
        )
        assert args.knowledge_path == Path("custom/.knowledge")


class TestParseQueryArgs:
    """Tests for parse_query_args function."""

    def test_optional_filters(self) -> None:
        """Should accept optional filters."""
        args = parse_query_args([])
        assert args.domain is None
        assert args.pattern is None
        assert args.entity is None
        assert args.fact_id is None

    def test_default_knowledge_path(self) -> None:
        """Should use default knowledge path."""
        args = parse_query_args([])
        assert args.knowledge_path == Path(".knowledge")

    def test_all_filters(self) -> None:
        """Should parse all filter options."""
        args = parse_query_args(
            [
                "--domain",
                "fastapi",
                "--pattern",
                "factory",
                "--entity",
                "create_app",
                "--fact-id",
                "uuid-123",
            ]
        )
        assert args.domain == "fastapi"
        assert args.pattern == "factory"
        assert args.entity == "create_app"
        assert args.fact_id == "uuid-123"


class TestParseDecorateArgs:
    """Tests for parse_decorate_args function."""

    def test_required_args(self) -> None:
        """Should require yaml-file and element-id."""
        args = parse_decorate_args(
            ["--yaml-file", "test.yml", "--element-id", "elem-1", "--entity", "e"]
        )
        assert args.yaml_file == Path("test.yml")
        assert args.element_id == "elem-1"

    def test_fact_ids_list(self) -> None:
        """Should parse multiple fact IDs."""
        args = parse_decorate_args(
            [
                "--yaml-file",
                "test.yml",
                "--element-id",
                "elem-1",
                "--fact-ids",
                "uuid-1",
                "uuid-2",
                "uuid-3",
            ]
        )
        assert args.fact_ids == ["uuid-1", "uuid-2", "uuid-3"]

    def test_dry_run_flag(self) -> None:
        """Should parse dry-run flag."""
        args = parse_decorate_args(
            [
                "--yaml-file",
                "test.yml",
                "--element-id",
                "elem-1",
                "--entity",
                "e",
                "--dry-run",
            ]
        )
        assert args.dry_run is True


class TestStoreFactMain:
    """Tests for store_fact_main function."""

    def test_returns_error_for_missing_extractions_csv(self, tmp_path: Path) -> None:
        """Should return 1 when extractions.csv doesn't exist."""
        args = argparse.Namespace(
            entity="create_app",
            domain="fastapi",
            pattern="factory",
            source_file="",
            source_element_id="",
            knowledge_path=tmp_path,
        )

        result = store_fact_main(args)

        assert result == 1

    def test_returns_success_for_no_facts(self, tmp_path: Path) -> None:
        """Should return 0 when no facts found for entity."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        extractions_csv = facts_dir / "extractions.csv"
        extractions_csv.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,iteration,confidence,extracted_at\n"
            "id-1,sent,other_entity,fact,residual,1,0.9,2024-01-01\n"
        )

        args = argparse.Namespace(
            entity="nonexistent",
            domain="fastapi",
            pattern="factory",
            source_file="",
            source_element_id="",
            knowledge_path=tmp_path,
        )

        result = store_fact_main(args)

        assert result == 0

    def test_stores_facts_to_yaml(self, tmp_path: Path) -> None:
        """Should store facts to domain/pattern YAML file."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        extractions_csv = facts_dir / "extractions.csv"
        extractions_csv.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,iteration,confidence,extracted_at\n"
            "id-1,sent,create_app,fact about create_app,residual,1,0.9,2024-01-01\n"
        )

        args = argparse.Namespace(
            entity="create_app",
            domain="fastapi",
            pattern="factory",
            source_file="docs/test.yml",
            source_element_id="elem-1",
            knowledge_path=tmp_path,
        )

        result = store_fact_main(args)

        assert result == 0
        yaml_path = facts_dir / "fastapi.factory.facts.yml"
        assert yaml_path.exists()
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert len(data["facts"]) == 1
        assert data["facts"][0]["entity"] == "create_app"


class TestQueryFactsMain:
    """Tests for query_facts_main function."""

    def test_returns_success_for_no_facts(self, tmp_path: Path) -> None:
        """Should return 0 when no facts found."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()

        args = argparse.Namespace(
            domain=None,
            pattern=None,
            entity=None,
            fact_id=None,
            knowledge_path=tmp_path,
        )

        result = query_facts_main(args)

        assert result == 0

    def test_displays_filtered_facts(self, tmp_path: Path) -> None:
        """Should display facts matching filters."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        (facts_dir / "fastapi.factory.facts.yml").write_text(
            yaml.dump(
                {
                    "facts": [
                        {
                            "fact_id": "id-1",
                            "entity": "create_app",
                            "fact_text": "test fact",
                            "domain": "fastapi",
                            "pattern": "factory",
                            "confidence": "0.9",
                        }
                    ]
                }
            )
        )

        args = argparse.Namespace(
            domain="fastapi",
            pattern=None,
            entity=None,
            fact_id=None,
            knowledge_path=tmp_path,
        )

        result = query_facts_main(args)

        assert result == 0

    def test_query_by_fact_id(self, tmp_path: Path) -> None:
        """Should query specific fact by ID."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()
        (facts_dir / "test.domain.facts.yml").write_text(
            yaml.dump(
                {
                    "facts": [
                        {
                            "fact_id": "target-id",
                            "entity": "test",
                            "fact_text": "target fact",
                            "domain": "test",
                            "pattern": "domain",
                            "confidence": "0.9",
                            "source_file": "",
                            "source_element_id": "",
                            "extracted_at": "2024-01-01",
                        }
                    ]
                }
            )
        )

        args = argparse.Namespace(
            domain=None,
            pattern=None,
            entity=None,
            fact_id="target-id",
            knowledge_path=tmp_path,
        )

        result = query_facts_main(args)

        assert result == 0


class TestDecorateYamlMain:
    """Tests for decorate_yaml_main function."""

    def test_returns_error_for_missing_yaml(self, tmp_path: Path) -> None:
        """Should return 1 when YAML file doesn't exist."""
        args = argparse.Namespace(
            yaml_file=tmp_path / "nonexistent.yml",
            element_id="elem-1",
            fact_ids=["uuid-1"],
            entity=None,
            knowledge_path=tmp_path,
            dry_run=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = decorate_yaml_main(args)

        assert result == 1

    def test_returns_error_when_no_decoration_specified(self, tmp_path: Path) -> None:
        """Should return 1 when neither fact_ids nor entity provided."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n")

        args = argparse.Namespace(
            yaml_file=yaml_path,
            element_id="elem-1",
            fact_ids=[],
            entity=None,
            knowledge_path=tmp_path,
            dry_run=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = decorate_yaml_main(args)

        assert result == 1

    def test_decorates_with_fact_ids(self, tmp_path: Path) -> None:
        """Should decorate element with fact IDs."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test\n")

        args = argparse.Namespace(
            yaml_file=yaml_path,
            element_id="elem-1",
            fact_ids=["uuid-1", "uuid-2"],
            entity=None,
            knowledge_path=tmp_path,
            dry_run=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = decorate_yaml_main(args)

        assert result == 0
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["items"][0]["fact_ids"] == ["uuid-1", "uuid-2"]

    def test_decorates_with_entity_id(self, tmp_path: Path) -> None:
        """Should decorate element with entity ID from variants."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test\n")

        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        variants_csv = keywords_dir / "variant_candidates.csv"
        variants_csv.write_text(
            "pair_id,keyword_a,keyword_b,similarity,merge,canonical,reason,validated\n"
            "entity-id,create_app,createApp,0.95,true,create_app,merged,true\n"
        )

        args = argparse.Namespace(
            yaml_file=yaml_path,
            element_id="elem-1",
            fact_ids=[],
            entity="create_app",
            knowledge_path=tmp_path,
            dry_run=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = decorate_yaml_main(args)

        assert result == 0
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["items"][0]["entity_id"] == "entity-id"

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        """Should not modify file in dry run mode."""
        yaml_path = tmp_path / "test.yml"
        original = "items:\n  - id: elem-1\n    text: Test\n"
        yaml_path.write_text(original)

        args = argparse.Namespace(
            yaml_file=yaml_path,
            element_id="elem-1",
            fact_ids=["uuid-1"],
            entity=None,
            knowledge_path=tmp_path,
            dry_run=True,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = decorate_yaml_main(args)

        assert result == 0
        assert yaml_path.read_text() == original


# --- Tests for structural facts and JSONL export ---


class TestDeterminePrimaryDomain:
    """Tests for determine_primary_domain function."""

    def test_single_domain_returns_domain(self) -> None:
        """Single domain returns that domain."""
        assert determine_primary_domain(["rest"]) == "rest"
        assert determine_primary_domain(["fastapi"]) == "fastapi"

    def test_multiple_domains_returns_first_domain(self) -> None:
        """Multiple domains returns the first domain in the list."""
        assert determine_primary_domain(["rest", "fastapi"]) == "rest"
        assert determine_primary_domain(["fastapi", "rest", "python"]) == "fastapi"

    def test_empty_list_returns_general(self) -> None:
        """Empty list returns 'general' as fallback."""
        assert determine_primary_domain([]) == "general"


class TestFieldfactToStructuralRecord:
    """Tests for fieldfact_to_structural_record function."""

    def test_basic_conversion(self) -> None:
        """Basic FieldFact to StructuralFactRecord conversion."""
        field_fact = FieldFact(
            element_id="elem-1",
            field_path="http_method_defaults[0].method",
            key="method",
            scope_path="http_method_defaults[0]",
            value="GET",
            value_kind="scalar-str",
            role="constraint",
            group_key="http_method_defaults::method=GET",
            group_id="abc123",
            source_file="docs/test.yml",
        )

        record = fieldfact_to_structural_record(
            field_fact,
            domains=["rest", "fastapi"],
            pattern="api",
            fact_id="uuid-1",
            extracted_at="2025-01-01T00:00:00Z",
        )

        assert record["fact_id"] == "uuid-1"
        assert record["element_id"] == "elem-1"
        assert record["field_path"] == "http_method_defaults[0].method"
        assert record["key"] == "method"
        assert record["scope_path"] == "http_method_defaults[0]"
        assert record["value"] == "GET"
        assert record["value_kind"] == "scalar-str"
        assert record["role"] == "constraint"
        assert record["domains"] == ["rest", "fastapi"]
        assert record["pattern"] == "api"
        assert record["confidence"] == 1.0
        assert record["extracted_at"] == "2025-01-01T00:00:00Z"

    def test_ref_value_serialization(self) -> None:
        """$ref dict values are serialized correctly."""
        field_fact = FieldFact(
            element_id="elem-1",
            field_path="refs[0].target",
            key="target",
            scope_path="refs[0]",
            value={"$ref": "other-element"},
            value_kind="ref",
            role="entity_ref",
            group_key="refs",
            group_id="def456",
            source_file="docs/test.yml",
        )

        record = fieldfact_to_structural_record(
            field_fact,
            domains=["rest"],
            pattern="api",
            fact_id="uuid-2",
            extracted_at="2025-01-01T00:00:00Z",
        )

        assert record["value"] == "$ref:other-element"

    def test_list_value_serialization(self) -> None:
        """List values are JSON serialized."""
        field_fact = FieldFact(
            element_id="elem-1",
            field_path="tags",
            key="tags",
            scope_path="",
            value=["tag1", "tag2"],
            value_kind="list-scalar",
            role="metadata",
            group_key="tags",
            group_id="ghi789",
            source_file="docs/test.yml",
        )

        record = fieldfact_to_structural_record(
            field_fact,
            domains=["rest"],
            pattern="api",
            fact_id="uuid-3",
            extracted_at="2025-01-01T00:00:00Z",
        )

        assert record["value"] == '["tag1", "tag2"]'


class TestStoreStructuralFacts:
    """Tests for store_structural_facts function."""

    def test_stores_fieldfacts_to_yaml(self, tmp_path: Path) -> None:
        """Stores FieldFacts to structural_facts section in YAML."""
        knowledge_path = tmp_path
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        field_facts = [
            FieldFact(
                element_id="elem-1",
                field_path="method",
                key="method",
                scope_path="",
                value="GET",
                value_kind="scalar-str",
                role="constraint",
                group_key="method",
                group_id="abc123",
                source_file="docs/test.yml",
            ),
        ]

        success, total = store_structural_facts(field_facts, ["rest"], "api", knowledge_path)

        assert success == 1
        assert total == 1

        yaml_path = facts_dir / "rest.api.facts.yml"
        assert yaml_path.exists()

        data = yaml.safe_load(yaml_path.read_text())
        assert "structural_facts" in data
        assert len(data["structural_facts"]) == 1
        assert data["structural_facts"][0]["element_id"] == "elem-1"
        assert data["structural_facts"][0]["value"] == "GET"

    def test_multi_domain_creates_first_domain_filename(self, tmp_path: Path) -> None:
        """Multi-domain facts use first domain in filename."""
        knowledge_path = tmp_path
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        field_facts = [
            FieldFact(
                element_id="elem-1",
                field_path="method",
                key="method",
                scope_path="",
                value="POST",
                value_kind="scalar-str",
                role="constraint",
                group_key="method",
                group_id="xyz789",
                source_file="docs/test.yml",
            ),
        ]

        # With multiple domains, uses first domain prefix
        success, _total = store_structural_facts(
            field_facts, ["rest", "fastapi"], "api", knowledge_path
        )

        assert success == 1
        yaml_path = facts_dir / "rest.api.facts.yml"
        assert yaml_path.exists()

    def test_skips_duplicates(self, tmp_path: Path) -> None:
        """Duplicate element_id:field_path:value combinations are skipped."""
        knowledge_path = tmp_path
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        field_fact = FieldFact(
            element_id="elem-1",
            field_path="method",
            key="method",
            scope_path="",
            value="GET",
            value_kind="scalar-str",
            role="constraint",
            group_key="method",
            group_id="abc123",
            source_file="docs/test.yml",
        )

        # Store twice with same value
        store_structural_facts([field_fact], ["rest"], "api", knowledge_path)
        success, total = store_structural_facts([field_fact], ["rest"], "api", knowledge_path)

        assert success == 1  # Duplicate considered success
        assert total == 1

        # Only one fact stored
        yaml_path = facts_dir / "rest.api.facts.yml"
        data = yaml.safe_load(yaml_path.read_text())
        assert len(data["structural_facts"]) == 1

    def test_stores_different_values_same_path(self, tmp_path: Path) -> None:
        """Different values for same element_id:field_path are stored as separate facts."""
        knowledge_path = tmp_path
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir(parents=True)

        field_fact_get = FieldFact(
            element_id="elem-1",
            field_path="method",
            key="method",
            scope_path="",
            value="GET",
            value_kind="scalar-str",
            role="constraint",
            group_key="method",
            group_id="abc123",
            source_file="docs/test.yml",
        )

        field_fact_post = FieldFact(
            element_id="elem-1",
            field_path="method",
            key="method",
            scope_path="",
            value="POST",  # Different value
            value_kind="scalar-str",
            role="constraint",
            group_key="method",
            group_id="abc123",
            source_file="docs/test.yml",
        )

        # Store first fact
        store_structural_facts([field_fact_get], ["rest"], "api", knowledge_path)
        # Store second fact with different value
        success, total = store_structural_facts([field_fact_post], ["rest"], "api", knowledge_path)

        assert success == 1
        assert total == 1

        # Both facts should be stored
        yaml_path = facts_dir / "rest.api.facts.yml"
        data = yaml.safe_load(yaml_path.read_text())
        assert len(data["structural_facts"]) == 2

        values = {f["value"] for f in data["structural_facts"]}
        assert values == {"GET", "POST"}

    def test_empty_list_returns_zeros(self, tmp_path: Path) -> None:
        """Empty FieldFacts list returns (0, 0)."""
        success, total = store_structural_facts([], ["rest"], "api", tmp_path)
        assert success == 0
        assert total == 0


class TestContainmentEdgesToEdgeRecords:
    """Tests for containment_edges_to_edge_records function."""

    def test_converts_containment_edges(self) -> None:
        """Converts ContainmentEdge to EdgeRecord."""
        edges = [
            ContainmentEdge(
                parent_id="parent-1",
                child_id="child-1",
                field_path="items[0]",
                source_file="docs/test.yml",
            ),
        ]

        records = containment_edges_to_edge_records(edges)

        assert len(records) == 1
        assert records[0]["edge_type"] == "containment"
        assert records[0]["source_id"] == "parent-1"
        assert records[0]["target_id"] == "child-1"
        assert records[0]["source_file"] == "docs/test.yml"
        assert records[0]["metadata"]["field_path"] == "items[0]"

    def test_generates_unique_edge_ids(self) -> None:
        """Each edge gets a unique edge_id."""
        edges = [
            ContainmentEdge("p1", "c1", "a[0]", "test.yml"),
            ContainmentEdge("p2", "c2", "b[0]", "test.yml"),
        ]

        records = containment_edges_to_edge_records(edges)

        assert len(records) == 2
        assert records[0]["edge_id"] != records[1]["edge_id"]


class TestEntityRefFieldfactsToEdgeRecords:
    """Tests for entity_ref_fieldfacts_to_edge_records function."""

    def test_extracts_entity_ref_edges(self) -> None:
        """Extracts edges from FieldFacts with role=='entity_ref'."""
        facts = [
            FieldFact(
                element_id="elem-1",
                field_path="refs[0]",
                key="target",
                scope_path="refs",
                value={"$ref": "target-elem"},
                value_kind="ref",
                role="entity_ref",
                group_key="refs",
                group_id="abc",
                source_file="docs/test.yml",
            ),
            FieldFact(
                element_id="elem-2",
                field_path="method",
                key="method",
                scope_path="",
                value="GET",
                value_kind="scalar-str",
                role="constraint",
                group_key="method",
                group_id="xyz",
                source_file="docs/test.yml",
            ),
        ]

        records = entity_ref_fieldfacts_to_edge_records(facts)

        assert len(records) == 1  # Only entity_ref role
        assert records[0]["edge_type"] == "entity_ref"
        assert records[0]["source_id"] == "elem-1"
        assert records[0]["target_id"] == "target-elem"
        assert records[0]["metadata"]["field_path"] == "refs[0]"

    def test_handles_string_ref_values(self) -> None:
        """Handles string values (not $ref dicts) for entity references."""
        facts = [
            FieldFact(
                element_id="elem-1",
                field_path="refs[0]",
                key="target",
                scope_path="refs",
                value="$ref:target-elem",  # Serialized format
                value_kind="ref",
                role="entity_ref",
                group_key="refs",
                group_id="abc",
                source_file="docs/test.yml",
            ),
        ]

        records = entity_ref_fieldfacts_to_edge_records(facts)

        assert len(records) == 1
        assert records[0]["target_id"] == "target-elem"


class TestQueryStructuralFacts:
    """Tests for query_structural_facts function."""

    def test_queries_by_domain_pattern(self, tmp_path: Path) -> None:
        """Queries structural facts by domain and pattern."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()

        yaml_content = {
            "facts": [],
            "structural_facts": [
                {
                    "fact_id": "uuid-1",
                    "element_id": "elem-1",
                    "field_path": "method",
                    "role": "constraint",
                },
            ],
        }
        (facts_dir / "rest.api.facts.yml").write_text(yaml.dump(yaml_content))

        results = query_structural_facts(facts_dir, domain="rest", pattern="api")

        assert len(results) == 1
        assert results[0]["element_id"] == "elem-1"

    def test_filters_by_element_id(self, tmp_path: Path) -> None:
        """Filters structural facts by element_id."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()

        yaml_content = {
            "facts": [],
            "structural_facts": [
                {"fact_id": "uuid-1", "element_id": "elem-1", "role": "constraint"},
                {"fact_id": "uuid-2", "element_id": "elem-2", "role": "constraint"},
            ],
        }
        (facts_dir / "rest.api.facts.yml").write_text(yaml.dump(yaml_content))

        results = query_structural_facts(facts_dir, element_id="elem-1")

        assert len(results) == 1
        assert results[0]["element_id"] == "elem-1"

    def test_filters_by_role(self, tmp_path: Path) -> None:
        """Filters structural facts by role."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir()

        yaml_content = {
            "facts": [],
            "structural_facts": [
                {"fact_id": "uuid-1", "element_id": "elem-1", "role": "constraint"},
                {"fact_id": "uuid-2", "element_id": "elem-2", "role": "entity_ref"},
            ],
        }
        (facts_dir / "rest.api.facts.yml").write_text(yaml.dump(yaml_content))

        results = query_structural_facts(facts_dir, role="entity_ref")

        assert len(results) == 1
        assert results[0]["role"] == "entity_ref"


class TestExportFactsToJsonl:
    """Tests for export_facts_to_jsonl function."""

    def test_exports_semantic_facts(self, tmp_path: Path) -> None:
        """Exports semantic facts to JSONL with source_field_path."""
        knowledge_path = tmp_path
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir()

        yaml_content = {
            "facts": [
                {
                    "fact_id": "uuid-1",
                    "entity": "create_app",
                    "fact_text": "Test fact",
                    "domain": "fastapi",
                    "pattern": "factory",
                    "confidence": 0.95,
                    "source_file": "docs/test.yml",
                    "source_element_id": "elem-1",
                    "source_field_path": "description.text",
                },
            ],
            "structural_facts": [],
        }
        (facts_dir / "fastapi.factory.facts.yml").write_text(yaml.dump(yaml_content))

        output_path = export_facts_to_jsonl(knowledge_path, include_edges=False)

        assert output_path.exists()
        with open(output_path) as f:
            records = [json.loads(line) for line in f]

        assert len(records) == 1
        assert records[0]["record_type"] == "fact"
        assert records[0]["fact_type"] == "semantic"
        assert records[0]["entity"] == "create_app"
        assert records[0]["source_field_path"] == "description.text"

    def test_exports_structural_facts(self, tmp_path: Path) -> None:
        """Exports structural facts to JSONL."""
        knowledge_path = tmp_path
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir()

        yaml_content = {
            "facts": [],
            "structural_facts": [
                {
                    "fact_id": "uuid-1",
                    "element_id": "elem-1",
                    "field_path": "method",
                    "role": "constraint",
                    "domains": ["rest", "fastapi"],
                },
            ],
        }
        (facts_dir / "rest.api.facts.yml").write_text(yaml.dump(yaml_content))

        output_path = export_facts_to_jsonl(knowledge_path, include_edges=False)

        with open(output_path) as f:
            records = [json.loads(line) for line in f]

        assert len(records) == 1
        assert records[0]["record_type"] == "fact"
        assert records[0]["fact_type"] == "structural"
        assert records[0]["element_id"] == "elem-1"
        assert records[0]["domains"] == ["rest", "fastapi"]

    def test_includes_entity_ref_edges(self, tmp_path: Path) -> None:
        """Includes entity_ref edges when include_edges=True."""
        knowledge_path = tmp_path
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir()

        yaml_content = {
            "facts": [],
            "structural_facts": [
                {
                    "fact_id": "uuid-1",
                    "element_id": "elem-1",
                    "field_path": "refs[0]",
                    "key": "ref_key",
                    "value": "$ref:target-elem",
                    "role": "entity_ref",
                    "source_file": "test.yml",
                },
            ],
        }
        (facts_dir / "rest.api.facts.yml").write_text(yaml.dump(yaml_content))

        output_path = export_facts_to_jsonl(knowledge_path, include_edges=True)

        with open(output_path) as f:
            records = [json.loads(line) for line in f]

        # Should have both fact and edge
        fact_records = [r for r in records if r["record_type"] == "fact"]
        edge_records = [r for r in records if r["record_type"] == "edge"]

        assert len(fact_records) == 1
        assert len(edge_records) == 1

        edge = edge_records[0]
        assert edge["edge_type"] == "entity_ref"
        assert edge["source_id"] == "elem-1"
        assert edge["target_id"] == "target-elem"
        assert edge["source_file"] == "test.yml"
        assert edge["metadata"]["field_path"] == "refs[0]"
        assert edge["metadata"]["key"] == "ref_key"

    def test_custom_output_path(self, tmp_path: Path) -> None:
        """Uses custom output path when provided."""
        knowledge_path = tmp_path
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir()

        yaml_content = {"facts": [], "structural_facts": []}
        (facts_dir / "rest.api.facts.yml").write_text(yaml.dump(yaml_content))

        custom_path = tmp_path / "custom" / "output.jsonl"
        output_path = export_facts_to_jsonl(
            knowledge_path, include_edges=False, output_path=custom_path
        )

        assert output_path == custom_path
        assert custom_path.exists()


class TestParseStoreStructuralArgs:
    """Tests for parse_store_structural_args function."""

    def test_parses_required_args(self) -> None:
        """Parses required arguments."""
        args = parse_store_structural_args(
            [
                "--yaml-file",
                "test.yml",
                "--domains",
                "rest",
                "fastapi",
                "--pattern",
                "api",
            ]
        )

        assert args.yaml_file == Path("test.yml")
        assert args.domains == ["rest", "fastapi"]
        assert args.pattern == "api"
        assert args.knowledge_path == Path(".knowledge")


class TestParseExportJsonlArgs:
    """Tests for parse_export_jsonl_args function."""

    def test_parses_default_args(self) -> None:
        """Parses with default values."""
        args = parse_export_jsonl_args([])

        assert args.knowledge_path == Path(".knowledge")
        assert args.output is None
        assert args.include_edges is True

    def test_parses_no_edges_flag(self) -> None:
        """Parses --no-edges flag."""
        args = parse_export_jsonl_args(["--no-edges"])

        assert args.include_edges is False


class TestIntegrationStructuralAndSemanticFacts:
    """Integration tests for structural and semantic facts workflow."""

    def test_stores_and_exports_both_fact_types(self, tmp_path: Path) -> None:
        """End-to-end: store structural facts, add semantic facts, export to JSONL."""
        knowledge_path = tmp_path
        facts_dir = knowledge_path / "facts"
        facts_dir.mkdir()

        # Store structural facts
        field_facts = [
            FieldFact(
                element_id="elem-1",
                field_path="method",
                key="method",
                scope_path="",
                value="GET",
                value_kind="scalar-str",
                role="constraint",
                group_key="method",
                group_id="abc123",
                source_file="docs/test.yml",
            ),
        ]
        store_structural_facts(field_facts, ["rest"], "api", knowledge_path)

        # Add semantic fact to same file
        yaml_path = facts_dir / "rest.api.facts.yml"
        data = yaml.safe_load(yaml_path.read_text())
        data["facts"].append(
            {
                "fact_id": "sem-uuid-1",
                "entity": "GET method",
                "fact_text": "GET is used for read operations",
                "domain": "rest",
                "pattern": "api",
                "confidence": 0.9,
            }
        )
        yaml_path.write_text(yaml.dump(data))

        # Export to JSONL
        output_path = export_facts_to_jsonl(knowledge_path, include_edges=False)

        with open(output_path) as f:
            records = [json.loads(line) for line in f]

        structural = [r for r in records if r["fact_type"] == "structural"]
        semantic = [r for r in records if r["fact_type"] == "semantic"]

        assert len(structural) == 1
        assert len(semantic) == 1
        assert structural[0]["element_id"] == "elem-1"
        assert semantic[0]["entity"] == "GET method"
