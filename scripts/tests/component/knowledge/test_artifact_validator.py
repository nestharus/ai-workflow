from pathlib import Path
from typing import Any

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from scripts.knowledge.artifact_validator import (
    ValidationResult,
    _compute_hash,
    _normalize_whitespace,
    _validate_exact_normalized,
    _validate_normalized_diff,
    _validate_normalized_rows_by_discriminator,
    _validate_normalized_text,
    _validate_structure_and_leaf_text,
    get_comparator_for_artifact_kind,
    load_validation_results,
    validate_artifact,
    write_validation_result,
)


@pytest.fixture
def sample_manifest() -> dict[str, Any]:
    """Create a sample artifact manifest for testing."""
    return {
        "artifact_id": "abc123def456789012345678901234567890123456789012345678901234",
        "artifact_kind": "prose/paragraph",
        "artifact_format": "text/markdown",
        "source": {
            "source_file": "docs/test.yml",
            "source_element_id": "test-element-1",
            "field_path": "description",
            "source_locator": "inline",
            "source_uri": None,
        },
        "render_plan_id": "prose.paragraph.v1",
        "projection_version": "fieldfacts.v2",
    }


@pytest.fixture
def validations_csv(fs: FakeFilesystem) -> Path:
    """Create a fake validations CSV path."""
    csv_path = Path("/fake/.knowledge/artifacts/validations.csv")
    fs.create_dir(csv_path.parent)
    return csv_path


class TestComputeHash:
    def test_computes_sha256_hash(self) -> None:
        """Verify SHA-256 hash is computed."""
        result = _compute_hash("test content")

        # Expected SHA-256 hash of "test content"
        assert len(result) == 64
        assert result == "6ae8a75555209fd6c44157c0aed8016e763ff435a19cf186f76863140143ff72"

    def test_different_inputs_different_hashes(self) -> None:
        """Verify different inputs produce different hashes."""
        hash1 = _compute_hash("content1")
        hash2 = _compute_hash("content2")

        assert hash1 != hash2

    def test_same_input_same_hash(self) -> None:
        """Verify same input produces same hash."""
        hash1 = _compute_hash("same content")
        hash2 = _compute_hash("same content")

        assert hash1 == hash2


class TestNormalizeWhitespace:
    def test_trims_whitespace(self) -> None:
        """Verify leading/trailing whitespace is trimmed."""
        result = _normalize_whitespace("  content  ")
        assert result == "content"

    def test_normalizes_newlines(self) -> None:
        """Verify newlines are normalized."""
        result = _normalize_whitespace("line1\r\nline2\rline3")
        assert result == "line1\nline2\nline3"

    def test_collapses_multiple_spaces(self) -> None:
        """Verify multiple spaces are collapsed."""
        result = _normalize_whitespace("word1    word2")
        assert result == "word1 word2"

    def test_collapses_multiple_newlines(self) -> None:
        """Verify multiple newlines are collapsed."""
        result = _normalize_whitespace("para1\n\n\n\npara2")
        assert result == "para1\n\npara2"


class TestValidateNormalizedText:
    def test_identical_text_passes(self) -> None:
        """Verify identical text returns similarity 1.0."""
        similarity, passed, mismatch = _validate_normalized_text(
            "Same content here.",
            "Same content here.",
        )

        assert similarity == 1.0
        assert passed is True
        assert mismatch == ""

    def test_different_text_fails(self) -> None:
        """Verify very different text fails."""
        similarity, passed, mismatch = _validate_normalized_text(
            "abcd",
            "xyz123",
        )

        assert similarity < 0.8
        assert passed is False
        assert "similarity" in mismatch.lower()

    def test_handles_empty_source(self) -> None:
        """Verify empty source text is handled."""
        similarity, passed, mismatch = _validate_normalized_text("", "content")
        assert similarity == 0.0
        assert passed is False
        assert "empty" in mismatch.lower()

    def test_handles_empty_rendered(self) -> None:
        """Verify empty rendered text is handled."""
        similarity, passed, mismatch = _validate_normalized_text("content", "")
        assert similarity == 0.0
        assert passed is False
        assert "empty" in mismatch.lower()

    def test_handles_both_empty(self) -> None:
        """Verify both empty texts return success."""
        similarity, passed, _mismatch = _validate_normalized_text("", "")
        assert similarity == 1.0
        assert passed is True


class TestValidateNormalizedRowsByDiscriminator:
    def test_identical_tables_pass(self) -> None:
        """Verify identical tables pass validation."""
        table = """| method | default |
|--------|---------|
| GET | true |
| POST | false |"""

        similarity, passed, _mismatch = _validate_normalized_rows_by_discriminator(table, table)

        assert similarity == 1.0
        assert passed is True

    def test_missing_row_fails(self) -> None:
        """Verify missing row fails validation."""
        source = """| method | default |
|--------|---------|
| GET | true |
| POST | false |"""

        rendered = """| method | default |
|--------|---------|
| GET | true |"""

        _similarity, passed, mismatch = _validate_normalized_rows_by_discriminator(source, rendered)

        assert passed is False
        assert "Missing rows" in mismatch

    def test_extra_row_fails(self) -> None:
        """Verify extra row fails validation."""
        source = """| method | default |
|--------|---------|
| GET | true |"""

        rendered = """| method | default |
|--------|---------|
| GET | true |
| POST | false |"""

        _similarity, passed, mismatch = _validate_normalized_rows_by_discriminator(source, rendered)

        assert passed is False
        assert "Extra rows" in mismatch

    def test_header_mismatch_fails(self) -> None:
        """Verify header mismatch fails validation."""
        source = """| method | default |
|--------|---------|
| GET | true |"""

        rendered = """| method | value |
|--------|---------|
| GET | true |"""

        similarity, passed, mismatch = _validate_normalized_rows_by_discriminator(source, rendered)

        assert similarity == 0.0
        assert passed is False
        assert "Headers mismatch" in mismatch

    def test_handles_empty_table_with_header_only(self) -> None:
        """Verify handling of table with only header (less than 2 lines after split)."""
        source = "| method |"  # Only header, no separator or data
        rendered = "| method |"

        # parse_markdown_table returns ([], []) for tables with < 2 lines
        _headers, _rows = [], []
        similarity, passed, _mismatch = _validate_normalized_rows_by_discriminator(source, rendered)

        # Both are empty, so they match
        assert passed is True
        assert similarity == 1.0

    def test_handles_empty_line_in_table_data(self) -> None:
        """Verify empty lines in table data are skipped."""
        source = """| method | default |
|--------|---------|
| GET | true |

| POST | false |"""

        rendered = """| method | default |
|--------|---------|
| GET | true |
| POST | false |"""

        similarity, passed, _mismatch = _validate_normalized_rows_by_discriminator(source, rendered)

        # Empty line should be skipped, both tables have same data
        assert passed is True
        assert similarity == 1.0

    def test_handles_separator_like_line_in_data(self) -> None:
        """Verify lines starting with |- are skipped (separator lines)."""
        source = """| method | default |
|--------|---------|
| GET | true |
|--------|---------|
| POST | false |"""

        rendered = """| method | default |
|--------|---------|
| GET | true |
| POST | false |"""

        similarity, passed, _mismatch = _validate_normalized_rows_by_discriminator(source, rendered)

        # The extra separator line should be skipped
        assert passed is True
        assert similarity == 1.0


class TestValidateStructureAndLeafText:
    def test_identical_yaml_passes(self) -> None:
        """Verify identical YAML passes validation."""
        yaml_content = """key: value
nested:
  field: content"""

        similarity, passed, mismatch = _validate_structure_and_leaf_text(yaml_content, yaml_content)

        assert similarity == 1.0
        assert passed is True
        assert mismatch == ""

    def test_different_structure_fails(self) -> None:
        """Verify different structure fails validation."""
        source = "key: value"
        rendered = "different_key: value"

        _similarity, passed, mismatch = _validate_structure_and_leaf_text(source, rendered)

        assert passed is False
        assert "missing keys" in mismatch or "extra keys" in mismatch

    def test_different_value_fails(self) -> None:
        """Verify different leaf value fails validation."""
        source = "key: value1"
        rendered = "key: value2"

        _similarity, passed, mismatch = _validate_structure_and_leaf_text(source, rendered)

        assert passed is False
        assert "value mismatch" in mismatch

    def test_invalid_yaml_fails(self) -> None:
        """Verify invalid YAML fails validation."""
        source = "valid: yaml"
        rendered = "invalid: yaml: syntax: {{"

        similarity, passed, mismatch = _validate_structure_and_leaf_text(source, rendered)

        assert similarity == 0.0
        assert passed is False
        assert "parse error" in mismatch.lower()

    def test_type_mismatch_between_dict_and_list(self) -> None:
        """Verify type mismatch between dict and list is detected."""
        source = "key:\n  - item1\n  - item2"  # key is a list
        rendered = "key:\n  subkey: value"  # key is a dict

        _similarity, passed, mismatch = _validate_structure_and_leaf_text(source, rendered)

        assert passed is False
        assert "type mismatch" in mismatch

    def test_list_length_mismatch(self) -> None:
        """Verify list length mismatch is detected."""
        source = "items:\n  - a\n  - b\n  - c"
        rendered = "items:\n  - a\n  - b"

        _similarity, passed, mismatch = _validate_structure_and_leaf_text(source, rendered)

        assert passed is False
        assert "length mismatch" in mismatch

    def test_list_item_comparison(self) -> None:
        """Verify list items are compared recursively."""
        source = "items:\n  - name: item1\n  - name: item2"
        rendered = "items:\n  - name: item1\n  - name: different"

        _similarity, passed, mismatch = _validate_structure_and_leaf_text(source, rendered)

        assert passed is False
        assert "value mismatch" in mismatch

    def test_nested_list_comparison(self) -> None:
        """Verify nested lists are compared correctly."""
        source = "nested:\n  list:\n    - 1\n    - 2"
        rendered = "nested:\n  list:\n    - 1\n    - 3"

        _similarity, passed, mismatch = _validate_structure_and_leaf_text(source, rendered)

        assert passed is False
        assert "value mismatch" in mismatch


class TestValidateNormalizedDiff:
    def test_identical_code_passes(self) -> None:
        """Verify identical code blocks pass."""
        content = """Some prose here.

```python
def hello():
    print("Hello")
```"""

        similarity, passed, _mismatch = _validate_normalized_diff(content, content)

        assert similarity == 1.0
        assert passed is True

    def test_code_block_preserved(self) -> None:
        """Verify code must be preserved verbatim."""
        source = """```python
original()
```"""

        rendered = """```python
modified()
```"""

        _similarity, passed, mismatch = _validate_normalized_diff(source, rendered)

        assert passed is False
        assert "Code block" in mismatch

    def test_prose_formatting_flexible(self) -> None:
        """Verify prose formatting is flexible."""
        source = "Some   prose  with   spaces."
        rendered = "Some prose with spaces."

        _similarity, passed, _mismatch = _validate_normalized_diff(
            source, rendered, preserve_code_verbatim=False
        )

        # Without code blocks, it's just text comparison
        assert passed is True


class TestValidateExactNormalized:
    def test_identical_text_passes(self) -> None:
        """Verify identical text returns similarity 1.0."""
        similarity, passed, mismatch = _validate_exact_normalized(
            "graph TD\n    A-->B",
            "graph TD\n    A-->B",
        )

        assert similarity == 1.0
        assert passed is True
        assert mismatch == ""

    def test_whitespace_normalized_passes(self) -> None:
        """Verify whitespace differences are normalized."""
        similarity, passed, _mismatch = _validate_exact_normalized(
            "graph TD\n    A-->B  ",
            "  graph TD\n    A-->B",
        )

        assert similarity == 1.0
        assert passed is True

    def test_different_content_fails(self) -> None:
        """Verify different content fails even with high similarity."""
        _similarity, passed, mismatch = _validate_exact_normalized(
            "graph TD\n    A-->B",
            "graph TD\n    A-->C",  # Single character difference
        )

        assert passed is False
        assert "Exact match required" in mismatch

    def test_reports_similarity(self) -> None:
        """Verify similarity is reported in mismatch summary."""
        similarity, passed, mismatch = _validate_exact_normalized(
            "abcd",
            "abce",
        )

        assert passed is False
        assert "Similarity" in mismatch
        # Characters a, b, c are common; only d vs e differs
        assert similarity > 0


class TestGetComparatorForArtifactKind:
    def test_prose_paragraph_uses_normalized_text(self) -> None:
        """Verify prose/paragraph uses normalized_text comparator."""
        result = get_comparator_for_artifact_kind("prose/paragraph")
        assert result == "normalized_text"

    def test_prose_code_block_uses_normalized_diff(self) -> None:
        """Verify prose/code-block uses normalized_diff comparator."""
        result = get_comparator_for_artifact_kind("prose/code-block")
        assert result == "normalized_diff"

    def test_table_uses_rows_by_discriminator(self) -> None:
        """Verify table/* uses normalized_rows_by_discriminator comparator."""
        result = get_comparator_for_artifact_kind("table/discriminator-grouped")
        assert result == "normalized_rows_by_discriminator"

    def test_schema_uses_structure_and_leaf_text(self) -> None:
        """Verify schema/* uses structure_and_leaf_text comparator."""
        result = get_comparator_for_artifact_kind("schema/nested-hierarchy")
        assert result == "structure_and_leaf_text"

    def test_diagram_uses_exact_normalized(self) -> None:
        """Verify diagram/* uses exact_normalized comparator."""
        result = get_comparator_for_artifact_kind("diagram/mermaid.sequence")
        assert result == "exact_normalized"

    def test_unknown_defaults_to_normalized_text(self) -> None:
        """Verify unknown kinds default to normalized_text."""
        result = get_comparator_for_artifact_kind("unknown/type")
        assert result == "normalized_text"


class TestValidationResult:
    def test_default_values(self) -> None:
        """Verify default values are set."""
        result = ValidationResult()

        assert result.validation_id  # UUID is generated
        assert result.artifact_id == ""
        assert result.similarity_score == 0.0
        assert result.passed is False
        assert result.validated_at  # Timestamp is generated

    def test_custom_values(self) -> None:
        """Verify custom values are accepted."""
        result = ValidationResult(
            artifact_id="test-id",
            similarity_score=0.95,
            passed=True,
        )

        assert result.artifact_id == "test-id"
        assert result.similarity_score == 0.95
        assert result.passed is True


class TestWriteValidationResult:
    def test_creates_csv_with_headers(self, fs: FakeFilesystem, validations_csv: Path) -> None:
        """Verify CSV is created with headers."""
        result = ValidationResult(
            artifact_id="test-id",
            similarity_score=0.95,
            passed=True,
        )

        write_validation_result(result, validations_csv)

        assert validations_csv.exists()
        content = validations_csv.read_text()
        assert "validation_id" in content
        assert "artifact_id" in content
        assert "similarity_score" in content

    def test_appends_to_existing_csv(self, fs: FakeFilesystem, validations_csv: Path) -> None:
        """Verify results are appended to existing CSV."""
        result1 = ValidationResult(artifact_id="id-1", similarity_score=0.8)
        result2 = ValidationResult(artifact_id="id-2", similarity_score=0.9)

        write_validation_result(result1, validations_csv)
        write_validation_result(result2, validations_csv)

        content = validations_csv.read_text()
        assert "id-1" in content
        assert "id-2" in content
        # Headers should only appear once
        assert content.count("validation_id") == 1


class TestLoadValidationResults:
    def test_loads_existing_results(self, fs: FakeFilesystem, validations_csv: Path) -> None:
        """Verify results are loaded from CSV."""
        result1 = ValidationResult(artifact_id="id-1", similarity_score=0.8, passed=True)
        result2 = ValidationResult(artifact_id="id-2", similarity_score=0.9, passed=False)

        write_validation_result(result1, validations_csv)
        write_validation_result(result2, validations_csv)

        loaded = load_validation_results(validations_csv)

        assert len(loaded) == 2
        assert loaded[0].artifact_id == "id-1"
        assert loaded[0].similarity_score == 0.8
        assert loaded[0].passed is True
        assert loaded[1].artifact_id == "id-2"

    def test_returns_empty_for_missing_file(self, fs: FakeFilesystem) -> None:
        """Verify empty list returned for missing file."""
        result = load_validation_results(Path("/nonexistent.csv"))
        assert result == []


class TestValidateArtifact:
    def test_validates_artifact_successfully(
        self,
        fs: FakeFilesystem,
        sample_manifest: dict[str, Any],
    ) -> None:
        """Verify artifact validation works."""
        # Create rendered file
        rendered_path = Path("/fake/rendered/abc123.md")
        fs.create_file(rendered_path, contents="Test content here.")

        result = validate_artifact(
            sample_manifest,
            rendered_path,
            "Test content here.",
            "normalized_text",
        )

        assert result.artifact_id == sample_manifest["artifact_id"]
        assert result.similarity_score == 1.0
        assert result.passed is True
        assert result.source_hash
        assert result.rendered_hash

    def test_raises_for_missing_rendered_file(
        self, fs: FakeFilesystem, sample_manifest: dict[str, Any]
    ) -> None:
        """Verify FileNotFoundError raised for missing rendered file."""
        with pytest.raises(FileNotFoundError, match="Rendered artifact not found"):
            validate_artifact(
                sample_manifest,
                Path("/nonexistent.md"),
                "source text",
                "normalized_text",
            )

    def test_raises_for_unsupported_comparator(
        self, fs: FakeFilesystem, sample_manifest: dict[str, Any]
    ) -> None:
        """Verify ValueError raised for unsupported comparator."""
        rendered_path = Path("/fake/rendered/abc123.md")
        fs.create_file(rendered_path, contents="content")

        with pytest.raises(ValueError, match="Unsupported validation comparator"):
            validate_artifact(
                sample_manifest,
                rendered_path,
                "source text",
                "invalid_comparator",  # type: ignore[arg-type]
            )

    def test_validates_with_normalized_rows_by_discriminator(
        self, fs: FakeFilesystem, sample_manifest: dict[str, Any]
    ) -> None:
        """Verify validation with normalized_rows_by_discriminator comparator."""
        table = """| method | default |
|--------|---------|
| GET | true |
| POST | false |"""

        rendered_path = Path("/fake/rendered/table.md")
        fs.create_file(rendered_path, contents=table)

        result = validate_artifact(
            sample_manifest,
            rendered_path,
            table,
            "normalized_rows_by_discriminator",
        )

        assert result.similarity_score == 1.0
        assert result.passed is True

    def test_validates_with_structure_and_leaf_text(
        self, fs: FakeFilesystem, sample_manifest: dict[str, Any]
    ) -> None:
        """Verify validation with structure_and_leaf_text comparator."""
        yaml_content = "key: value\nnested:\n  field: content"

        rendered_path = Path("/fake/rendered/schema.yml")
        fs.create_file(rendered_path, contents=yaml_content)

        result = validate_artifact(
            sample_manifest,
            rendered_path,
            yaml_content,
            "structure_and_leaf_text",
        )

        assert result.similarity_score == 1.0
        assert result.passed is True

    def test_validates_with_normalized_diff(
        self, fs: FakeFilesystem, sample_manifest: dict[str, Any]
    ) -> None:
        """Verify validation with normalized_diff comparator."""
        content = """Some prose here.

```python
def hello():
    print("Hello")
```"""

        rendered_path = Path("/fake/rendered/code.md")
        fs.create_file(rendered_path, contents=content)

        result = validate_artifact(
            sample_manifest,
            rendered_path,
            content,
            "normalized_diff",
        )

        assert result.similarity_score == 1.0
        assert result.passed is True

    def test_validates_with_exact_normalized(
        self, fs: FakeFilesystem, sample_manifest: dict[str, Any]
    ) -> None:
        """Verify validation with exact_normalized comparator."""
        diagram = "graph TD\n    A-->B"

        rendered_path = Path("/fake/rendered/diagram.mmd")
        fs.create_file(rendered_path, contents=diagram)

        result = validate_artifact(
            sample_manifest,
            rendered_path,
            diagram,
            "exact_normalized",
        )

        assert result.similarity_score == 1.0
        assert result.passed is True
