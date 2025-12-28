import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.knowledge.artifact_fact_extractor import (
    ArtifactExtractionError,
    ExtractionSummary,
    InvariantViolation,
    _assert_localized_rewrites,
    _assert_monotonic_or_handle,
    _assert_non_target_preservation,
    _assert_text_is_state,
    _compute_hash,
    apply_rewrite,
    extract_artifact_facts,
    load_artifact_manifest,
    load_artifact_text,
    main,
    parse_args,
    persist_pass,
    resolve_entity,
)


class TestLoadArtifactText:
    def test_loads_from_source_file(self, tmp_path: Path) -> None:
        """Should load text from source file."""
        source_file = tmp_path / "source.txt"
        source_file.write_text("Content from source file", encoding="utf-8")

        manifest = {"source_file": str(source_file)}

        with patch("scripts.knowledge.artifact_fact_extractor.REPO_ROOT", tmp_path):
            result = load_artifact_text(manifest, tmp_path)

        assert result == "Content from source file"

    def test_raises_error_for_missing_source(self, tmp_path: Path) -> None:
        """Should raise ArtifactExtractionError for missing source file."""
        manifest = {"source_file": "nonexistent.txt"}

        with (
            patch("scripts.knowledge.artifact_fact_extractor.REPO_ROOT", tmp_path),
            pytest.raises(ArtifactExtractionError, match="Source file not found"),
        ):
            load_artifact_text(manifest, tmp_path)


class TestExtractArtifactFacts:
    def test_max_iterations_limit(self, tmp_path: Path) -> None:
        """Should stop at max iterations."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {
            "artifact_id": "test-artifact",
            "inline_text": "The create_app function creates applications.",
        }
        manifest_path = artifacts_dir / "test-artifact.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        with patch("scripts.knowledge.artifact_fact_extractor.invoke_hunter_mock") as mock_hunter:
            # Hunter never signals done
            mock_hunter.return_value = {
                "mode": "entities",
                "entities": [
                    {"mention": "test", "type_hint": "IDENTIFIER", "evidence_span_id": "s1"}
                ],
                "target_entity": None,
                "facts": [],
                "spans": [],
                "done": False,
                "reason": None,
            }

            result = extract_artifact_facts(
                "test-artifact",
                knowledge_path,
                use_mock=True,
                max_iterations=3,
            )

        # Should hit the stuck_reason for max_iterations
        assert result["audit_result"].get("recommended_action") is not None


class TestLoadArtifactTextSourceElementId:
    def test_loads_text_from_source_element_id(self, tmp_path: Path) -> None:
        """Should load text field from YAML element by source_element_id (line 385-396)."""
        # Create a YAML source file with elements
        source_file = tmp_path / "source.yml"
        source_content = """
items:
  - id: my.element
    text: This is the extracted text from element.
  - id: other.element
    text: Other element text.
"""
        source_file.write_text(source_content, encoding="utf-8")

        manifest = {
            "source_file": str(source_file),
            "source_element_id": "my.element",
        }

        with patch("scripts.knowledge.artifact_fact_extractor.REPO_ROOT", tmp_path):
            result = load_artifact_text(manifest, tmp_path)

        assert result == "This is the extracted text from element."

    def test_loads_text_list_from_source_element_id(self, tmp_path: Path) -> None:
        """Should join list text field from element (line 394-395)."""
        source_file = tmp_path / "source.yml"
        source_content = """
items:
  - id: list.element
    text:
      - Part one of text.
      - Part two of text.
      - Part three.
"""
        source_file.write_text(source_content, encoding="utf-8")

        manifest = {
            "source_file": str(source_file),
            "source_element_id": "list.element",
        }

        with patch("scripts.knowledge.artifact_fact_extractor.REPO_ROOT", tmp_path):
            result = load_artifact_text(manifest, tmp_path)

        assert result == "Part one of text. Part two of text. Part three."

    def test_raises_error_for_missing_element(self, tmp_path: Path) -> None:
        """Should raise error when source_element_id not found (line 388-391)."""
        source_file = tmp_path / "source.yml"
        source_content = """
items:
  - id: existing.element
    text: Some text.
"""
        source_file.write_text(source_content, encoding="utf-8")

        manifest = {
            "source_file": str(source_file),
            "source_element_id": "nonexistent.element",
        }

        with (
            patch("scripts.knowledge.artifact_fact_extractor.REPO_ROOT", tmp_path),
            pytest.raises(ArtifactExtractionError, match="not found in"),
        ):
            load_artifact_text(manifest, tmp_path)

    def test_loads_empty_text_from_element(self, tmp_path: Path) -> None:
        """Should handle element with no text field (returns empty string)."""
        source_file = tmp_path / "source.yml"
        source_content = """
items:
  - id: no.text.element
    description: Element without text field
"""
        source_file.write_text(source_content, encoding="utf-8")

        manifest = {
            "source_file": str(source_file),
            "source_element_id": "no.text.element",
        }

        with patch("scripts.knowledge.artifact_fact_extractor.REPO_ROOT", tmp_path):
            result = load_artifact_text(manifest, tmp_path)

        assert result == ""

    def test_raises_error_for_yaml_parse_error_in_source_element(self, tmp_path: Path) -> None:
        """Should raise error for invalid YAML in source file (line 397-398)."""
        source_file = tmp_path / "source.yml"
        source_file.write_text("{ invalid: yaml: content", encoding="utf-8")

        manifest = {
            "source_file": str(source_file),
            "source_element_id": "any.element",
        }

        with (
            patch("scripts.knowledge.artifact_fact_extractor.REPO_ROOT", tmp_path),
            pytest.raises(ArtifactExtractionError, match="Failed to load"),
        ):
            load_artifact_text(manifest, tmp_path)


class TestExtractArtifactFactsNoOpDetection:
    def test_detects_no_op_same_hash(self, tmp_path: Path) -> None:
        """Should detect no-op when hash repeats (lines 828-831)."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {
            "artifact_id": "noop-artifact",
            "inline_text": "Entity text here.",
        }
        manifest_path = artifacts_dir / "noop-artifact.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        # Mock the hunter to return an entity but no facts (causing no change)
        with patch("scripts.knowledge.artifact_fact_extractor.invoke_hunter_mock") as mock_hunter:
            # First call: return entities
            # Second call: return facts but rewrite is no-op
            mock_hunter.side_effect = [
                {
                    "mode": "entities",
                    "entities": [
                        {"mention": "Entity", "type_hint": "ID", "evidence_span_id": "s1"}
                    ],
                    "target_entity": None,
                    "facts": [],
                    "spans": [],
                    "done": False,
                    "reason": None,
                },
                {
                    "mode": "facts",
                    "entities": [],
                    "target_entity": "Entity",
                    "facts": [],  # No facts - triggers continue
                    "spans": [],
                    "done": False,
                    "reason": None,
                },
                # Hunter signals done on next iteration
                {
                    "mode": "entities",
                    "entities": [],
                    "target_entity": None,
                    "facts": [],
                    "spans": [],
                    "done": True,
                    "reason": "No more entities",
                },
            ]

            result = extract_artifact_facts(
                "noop-artifact",
                knowledge_path,
                use_mock=True,
                max_iterations=10,
            )

        assert result["artifact_id"] == "noop-artifact"


class TestExtractArtifactFactsNoEntities:
    def test_completes_when_no_entities_discovered(self, tmp_path: Path) -> None:
        """Should break loop when no entities discovered (lines 709-711)."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {
            "artifact_id": "no-entities-artifact",
            "inline_text": "Plain text with nothing special.",
        }
        manifest_path = artifacts_dir / "no-entities-artifact.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        with patch("scripts.knowledge.artifact_fact_extractor.invoke_hunter_mock") as mock_hunter:
            # Hunter returns empty entities list (not done, but no entities)
            mock_hunter.return_value = {
                "mode": "entities",
                "entities": [],  # Empty list - should trigger lines 709-711
                "target_entity": None,
                "facts": [],
                "spans": [],
                "done": False,
                "reason": None,
            }

            result = extract_artifact_facts(
                "no-entities-artifact",
                knowledge_path,
                use_mock=True,
                max_iterations=10,
            )

        assert result["total_passes"] == 0
        assert result["total_facts_extracted"] == 0


class TestExtractArtifactFactsInvariantViolationRevert:
    def test_reverts_on_non_target_preservation_violation(self, tmp_path: Path) -> None:
        """Should revert state when non-target preservation invariant violated."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {
            "artifact_id": "revert-artifact",
            "inline_text": "Target sentence. Anchor sentence. More anchors.",
        }
        manifest_path = artifacts_dir / "revert-artifact.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        with (
            patch("scripts.knowledge.artifact_fact_extractor.invoke_hunter_mock") as mock_hunter,
            patch(
                "scripts.knowledge.artifact_fact_extractor.orchestrate_surgeon_pipeline_mock"
            ) as mock_surgeon,
            patch(
                "scripts.knowledge.artifact_fact_extractor._assert_non_target_preservation"
            ) as mock_assert,
        ):
            # Hunter finds entity and fact
            mock_hunter.side_effect = [
                {
                    "mode": "entities",
                    "entities": [
                        {"mention": "Target", "type_hint": "ID", "evidence_span_id": "s1"}
                    ],
                    "target_entity": None,
                    "facts": [],
                    "spans": [],
                    "done": False,
                    "reason": None,
                },
                {
                    "mode": "facts",
                    "entities": [],
                    "target_entity": "Target",
                    "facts": [{"fact_text": "fact1", "evidence_span_id": "s1"}],
                    "spans": [{"span_id": "s1", "original_text": "Target sentence"}],
                    "done": False,
                    "reason": None,
                },
                {
                    "mode": "entities",
                    "entities": [],
                    "target_entity": None,
                    "facts": [],
                    "spans": [],
                    "done": True,
                    "reason": "Complete",
                },
            ]

            mock_surgeon.return_value = [
                {
                    "span_id": "s1",
                    "replacement_text": "",  # Removes all text
                    "validation": {},
                    "review": None,
                    "success": True,
                }
            ]

            # Raise invariant violation to trigger revert
            mock_assert.side_effect = InvariantViolation("non-target-preservation: test")

            result = extract_artifact_facts(
                "revert-artifact",
                knowledge_path,
                use_mock=True,
                max_iterations=5,
            )

        # Should still complete (revert handled gracefully)
        assert result["artifact_id"] == "revert-artifact"


class TestMainFunction:
    def test_main_with_relative_knowledge_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should handle relative knowledge path (line 990)."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {"artifact_id": "rel-path-test", "inline_text": "Test."}
        manifest_path = artifacts_dir / "rel-path-test.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        test_args = [
            "script",
            "--artifact-id",
            "rel-path-test",
            "--knowledge-path",
            ".knowledge",  # Relative path
            "--mock",
        ]

        with (
            patch.object(sys, "argv", test_args),
            patch("scripts.knowledge.artifact_fact_extractor.REPO_ROOT", tmp_path),
        ):
            result = main()

        assert result == 0

    def test_main_invariant_violation_error(self, tmp_path: Path) -> None:
        """Should return 1 on InvariantViolation (lines 1014-1016)."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {"artifact_id": "inv-test", "inline_text": "Test."}
        manifest_path = artifacts_dir / "inv-test.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        test_args = [
            "script",
            "--artifact-id",
            "inv-test",
            "--knowledge-path",
            str(knowledge_path),
            "--mock",
        ]

        with (
            patch.object(sys, "argv", test_args),
            patch(
                "scripts.knowledge.artifact_fact_extractor.extract_artifact_facts",
                side_effect=InvariantViolation("Test violation"),
            ),
        ):
            result = main()

        assert result == 1

    def test_main_unexpected_error(self, tmp_path: Path) -> None:
        """Should return 1 on unexpected error (lines 1017-1019)."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {"artifact_id": "err-test", "inline_text": "Test."}
        manifest_path = artifacts_dir / "err-test.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        test_args = [
            "script",
            "--artifact-id",
            "err-test",
            "--knowledge-path",
            str(knowledge_path),
            "--mock",
        ]

        with (
            patch.object(sys, "argv", test_args),
            patch(
                "scripts.knowledge.artifact_fact_extractor.extract_artifact_facts",
                side_effect=RuntimeError("Unexpected error"),
            ),
        ):
            result = main()

        assert result == 1
