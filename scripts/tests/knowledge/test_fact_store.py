"""Tests for scripts.knowledge.fact_store module."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.knowledge.fact_store import (
    FactStoreRecord,
    decorate_yaml_main,
    decorate_yaml_with_entity_id,
    decorate_yaml_with_fact_ids,
    ensure_fact_yaml_exists,
    get_entity_id_from_variants,
    get_fact_by_id,
    list_fact_files,
    organize_facts_by_domain_pattern,
    parse_decorate_args,
    parse_query_args,
    parse_store_args,
    query_facts_from_yaml,
    query_facts_main,
    read_facts_from_csv,
    store_fact_main,
    store_fact_to_yaml,
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

        result, updates = decorate_yaml_with_fact_ids(
            yaml_path, "elem-1", ["uuid-1", "uuid-2"]
        )

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

        result, updates = decorate_yaml_with_fact_ids(
            yaml_path, "elem-1", ["existing", "new"]
        )

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

        result, updates = decorate_yaml_with_fact_ids(
            yaml_path, "elem-1", ["existing"]
        )

        assert result == 0  # No new IDs added
        assert any("no new fact IDs to add" in u for u in updates)

    def test_returns_zero_for_missing_element(self, tmp_path: Path) -> None:
        """Should return 0 when element not found."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: other\n    text: Test\n")

        result, updates = decorate_yaml_with_fact_ids(
            yaml_path, "nonexistent", ["uuid-1"]
        )

        assert result == 0
        assert any("not found" in u for u in updates)

    def test_returns_zero_for_parse_failure(self, tmp_path: Path) -> None:
        """Should return 0 when YAML parse fails."""
        yaml_path = tmp_path / "invalid.yml"
        yaml_path.write_text("invalid: yaml: [")

        result, updates = decorate_yaml_with_fact_ids(
            yaml_path, "elem-1", ["uuid-1"]
        )

        assert result == 0
        assert updates == []

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        """Should not modify file in dry run mode but return count of IDs that would be added."""
        yaml_path = tmp_path / "test.yml"
        original = "items:\n  - id: elem-1\n    text: Test\n"
        yaml_path.write_text(original)

        result, updates = decorate_yaml_with_fact_ids(
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

        result, updates = decorate_yaml_with_entity_id(
            yaml_path, "elem-1", "create_app", "entity-uuid"
        )

        assert result == 1
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["items"][0]["entity_id"] == "entity-uuid"

    def test_overwrites_existing_entity_id(self, tmp_path: Path) -> None:
        """Should overwrite existing entity_id."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text(
            "items:\n  - id: elem-1\n    text: Test\n    entity_id: old-id\n"
        )

        result, updates = decorate_yaml_with_entity_id(
            yaml_path, "elem-1", "create_app", "new-id"
        )

        assert result == 1
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["items"][0]["entity_id"] == "new-id"

    def test_returns_zero_for_missing_element(self, tmp_path: Path) -> None:
        """Should return 0 when element not found."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: other\n    text: Test\n")

        result, updates = decorate_yaml_with_entity_id(
            yaml_path, "nonexistent", "entity", "uuid"
        )

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
        args = parse_store_args(
            ["--entity", "e", "--domain", "d", "--pattern", "p"]
        )
        assert args.knowledge_path == Path(".knowledge")

    def test_custom_knowledge_path(self) -> None:
        """Should accept custom knowledge path."""
        args = parse_store_args(
            [
                "--entity", "e",
                "--domain", "d",
                "--pattern", "p",
                "--knowledge-path", "custom/.knowledge",
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
                "--domain", "fastapi",
                "--pattern", "factory",
                "--entity", "create_app",
                "--fact-id", "uuid-123",
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
                "--yaml-file", "test.yml",
                "--element-id", "elem-1",
                "--fact-ids", "uuid-1", "uuid-2", "uuid-3",
            ]
        )
        assert args.fact_ids == ["uuid-1", "uuid-2", "uuid-3"]

    def test_dry_run_flag(self) -> None:
        """Should parse dry-run flag."""
        args = parse_decorate_args(
            [
                "--yaml-file", "test.yml",
                "--element-id", "elem-1",
                "--entity", "e",
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
