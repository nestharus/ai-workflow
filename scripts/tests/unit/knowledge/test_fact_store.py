import argparse
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.knowledge.fact_store import (
    FactProvenanceRecord,
    FactStoreRecord,
    append_provenance,
    compute_fact_key,
    containment_edges_to_edge_records,
    decorate_yaml_main,
    decorate_yaml_with_entity_id,
    decorate_yaml_with_fact_ids,
    determine_primary_domain,
    ensure_fact_yaml_exists,
    ensure_provenance_csv_exists,
    entity_ref_fieldfacts_to_edge_records,
    export_facts_to_jsonl,
    export_jsonl_main,
    fact_key_exists,
    fieldfact_to_structural_record,
    get_entity_id_from_variants,
    get_fact_by_id,
    list_fact_files,
    main_decorate,
    main_export_jsonl,
    main_query,
    main_store,
    main_store_structural,
    normalize_fact_text,
    organize_facts_by_domain_pattern,
    parse_decorate_args,
    parse_export_jsonl_args,
    parse_query_args,
    parse_store_args,
    parse_store_structural_args,
    query_fact_provenance,
    query_facts_from_yaml,
    query_facts_main,
    query_structural_facts,
    read_facts_from_csv,
    store_fact_main,
    store_fact_to_yaml,
    store_fact_with_deduplication,
    store_structural_facts,
    store_structural_main,
)


class TestDecorateYamlMain:
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


class TestDecorateYamlMainBranchCoverage:
    def test_absolute_knowledge_path_coverage(self, tmp_path: Path) -> None:
        """Should handle absolute knowledge path (line 1690-1693 branch)."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test\n")

        args = argparse.Namespace(
            yaml_file=yaml_path,
            element_id="elem-1",
            fact_ids=["uuid-1"],
            entity=None,
            knowledge_path=tmp_path,  # Absolute path - triggers line 1691-1692
            dry_run=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = decorate_yaml_main(args)

        # Element found, decoration succeeds
        assert result == 0

    def test_relative_knowledge_path_coverage(self, tmp_path: Path) -> None:
        """Should handle relative knowledge path (line 1693 branch)."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test\n")

        args = argparse.Namespace(
            yaml_file=yaml_path,
            element_id="elem-1",
            fact_ids=["uuid-1"],
            entity=None,
            knowledge_path=Path(".knowledge"),  # Relative path - triggers line 1693
            dry_run=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = decorate_yaml_main(args)

        # Element found, decoration succeeds
        assert result == 0

    def test_relative_yaml_path_coverage(self, tmp_path: Path) -> None:
        """Should handle relative yaml_file path (line 1696-1699 branch)."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test\n")

        args = argparse.Namespace(
            yaml_file=Path("test.yml"),  # Relative path - triggers line 1699
            element_id="elem-1",
            fact_ids=["uuid-1"],
            entity=None,
            knowledge_path=tmp_path,
            dry_run=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = decorate_yaml_main(args)

        # Element found, decoration succeeds
        assert result == 0

    def test_entity_id_decoration_failure(self, tmp_path: Path) -> None:
        """Should handle entity_id decoration returning failure (line 1747-1750)."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: other-elem\n    text: Test\n")

        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        variants_csv = keywords_dir / "variant_candidates.csv"
        # Entity present and validated in variants
        variants_csv.write_text(
            "pair_id,keyword_a,keyword_b,similarity,merge,canonical,reason,validated\n"
            "pid-1,entity_name,variant,0.9,true,entity_name,merged,true\n"
        )

        args = argparse.Namespace(
            yaml_file=yaml_path,
            element_id="missing-elem",  # Element doesn't exist
            fact_ids=[],
            entity="entity_name",  # Entity exists in variants
            knowledge_path=tmp_path,
            dry_run=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = decorate_yaml_main(args)

        # Element not found for entity decoration triggers has_failure (line 1749-1750)
        assert result == 1

    def test_entity_id_added_success(self, tmp_path: Path) -> None:
        """Should handle successful entity_id decoration (line 1749, 1757 branch)."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test\n")

        keywords_dir = tmp_path / "keywords"
        keywords_dir.mkdir()
        variants_csv = keywords_dir / "variant_candidates.csv"
        variants_csv.write_text(
            "pair_id,keyword_a,keyword_b,similarity,merge,canonical,reason,validated\n"
            "pid-1,entity_name,variant,0.9,true,entity_name,merged,true\n"
        )

        args = argparse.Namespace(
            yaml_file=yaml_path,
            element_id="elem-1",  # Element exists
            fact_ids=[],
            entity="entity_name",
            knowledge_path=tmp_path,
            dry_run=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = decorate_yaml_main(args)

        # Decoration successful
        assert result == 0


class TestExportJsonlMainCoverage:
    def test_relative_knowledge_path(self, tmp_path: Path) -> None:
        """Should handle relative knowledge path (line 1974)."""
        facts_dir = tmp_path / ".knowledge" / "facts"
        facts_dir.mkdir(parents=True)
        (facts_dir / "test.domain.facts.yml").write_text(yaml.dump({"facts": []}))

        args = argparse.Namespace(
            knowledge_path=Path(".knowledge"),  # Relative path - triggers line 1974
            output=None,
            include_edges=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = export_jsonl_main(args)

        assert result == 0

    def test_custom_output_path_relative(self, tmp_path: Path) -> None:
        """Should handle relative output path (line 1977-1978)."""
        facts_dir = tmp_path / "facts"
        facts_dir.mkdir(parents=True)
        (facts_dir / "test.domain.facts.yml").write_text(yaml.dump({"facts": []}))

        args = argparse.Namespace(
            knowledge_path=tmp_path,
            output=Path("output/custom.jsonl"),  # Relative triggers line 1978
            include_edges=False,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = export_jsonl_main(args)

        assert result == 0
        assert (tmp_path / "output" / "custom.jsonl").exists()


class TestQueryFactsMainRelativePath:
    def test_relative_knowledge_path(self, tmp_path: Path) -> None:
        """Should handle relative knowledge path (line 1584)."""
        facts_dir = tmp_path / ".knowledge" / "facts"
        facts_dir.mkdir(parents=True)
        (facts_dir / "test.domain.facts.yml").write_text(yaml.dump({"facts": []}))

        args = argparse.Namespace(
            domain=None,
            pattern=None,
            entity=None,
            fact_id=None,
            knowledge_path=Path(".knowledge"),  # Relative path triggers line 1584
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = query_facts_main(args)

        assert result == 0


class TestStoreFactMainRelativePath:
    def test_relative_knowledge_path(self, tmp_path: Path) -> None:
        """Should handle relative knowledge path (line 1490)."""
        knowledge_dir = tmp_path / ".knowledge"
        facts_dir = knowledge_dir / "facts"
        facts_dir.mkdir(parents=True)

        extractions_csv = facts_dir / "extractions.csv"
        extractions_csv.write_text(
            "fact_id,source_sentence,entity,fact_text,rewritten_sentence,"
            "iteration,confidence,extracted_at\n"
            "id-1,sent1,test_entity,fact1,residual1,1,0.9,2024-01-01\n"
        )

        args = argparse.Namespace(
            entity="test_entity",
            domain="test",
            pattern="pattern",
            source_file="",
            source_element_id="",
            knowledge_path=Path(".knowledge"),  # Relative path triggers line 1490
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = store_fact_main(args)

        assert result == 0


class TestStoreStructuralMainCoverage:
    def test_relative_knowledge_path(self, tmp_path: Path) -> None:
        """Should handle relative knowledge path (line 1862)."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test\n")

        args = argparse.Namespace(
            yaml_file=yaml_path,
            domains=["test"],
            pattern="pattern",
            knowledge_path=Path(".knowledge"),  # Relative path triggers line 1862
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = store_structural_main(args)

        assert result == 0

    def test_relative_yaml_path(self, tmp_path: Path) -> None:
        """Should handle relative yaml path (line 1868)."""
        yaml_path = tmp_path / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n    text: Test\n")

        args = argparse.Namespace(
            yaml_file=Path("test.yml"),  # Relative path triggers line 1868
            domains=["test"],
            pattern="pattern",
            knowledge_path=tmp_path,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = store_structural_main(args)

        assert result == 0

    def test_relative_path_computation(self, tmp_path: Path) -> None:
        """Should compute relative path correctly (line 1883-1886)."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        yaml_path = subdir / "test.yml"
        yaml_path.write_text("items:\n  - id: elem-1\n")

        args = argparse.Namespace(
            yaml_file=yaml_path,
            domains=["test"],
            pattern="pattern",
            knowledge_path=tmp_path,
        )

        with patch("scripts.knowledge.fact_store.REPO_ROOT", tmp_path):
            result = store_structural_main(args)

        assert result == 0
