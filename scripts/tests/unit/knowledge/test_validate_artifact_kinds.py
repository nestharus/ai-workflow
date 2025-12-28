from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from scripts.knowledge import validate_artifact_kinds
from scripts.knowledge.validate_artifact_kinds import (
    ValidationResult,
    _compute_jaccard_similarity,
    compute_pattern_signature,
    load_registry,
    main,
    parse_args,
    validate_duplicates,
    validate_registry,
    validate_samples,
    validate_schema,
    validate_structure_pattern_determinism,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestCLIIntegration:
    def test_json_report_write_error(self, fs: FakeFilesystem, capsys) -> None:
        """Should handle OSError when writing JSON report (lines 819-820)."""
        fs.create_dir("/fake/.knowledge/artifacts")
        registry_content = """
kinds:
  - kind_id: test/kind
    content_form: text
    structure_pattern:
      root_path: sections[*].text
    extraction_contract:
      contributors: []
    rendering_contract:
      render_plan_id: test.v1
"""
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents=registry_content,
        )
        # Create output directory
        fs.create_dir("/fake/output")

        def failing_write_text(self, data, encoding=None):
            if "report.json" in str(self):
                raise OSError("Permission denied")
            # Fall through to real pyfakefs write
            path_str = str(self)
            fs.create_file(path_str, contents=data)

        # Patch at the module level
        with (
            patch.object(validate_artifact_kinds, "REPO_ROOT", Path("/fake")),
            patch("pathlib.Path.write_text", failing_write_text),
        ):
            exit_code = main(
                [
                    "--knowledge-path",
                    "/fake/.knowledge",
                    "--json-report",
                    "/fake/output/report.json",
                ]
            )

        captured = capsys.readouterr()
        assert "Error writing JSON report" in captured.err
        # Should still return 0 since registry is valid
        assert exit_code == 0


class TestLoadRegistryAdditional:
    def test_os_error_reading_file(self, fs: FakeFilesystem) -> None:
        """Should return error message on OSError (lines 168-169)."""
        fs.create_dir("/fake/.knowledge/artifacts")
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents="kinds: []\n",
        )

        def mock_read_text(self, encoding=None):
            """Mock that raises OSError."""
            raise OSError("Disk read error")

        # Patch at the module level using pathlib.Path.read_text
        with patch("pathlib.Path.read_text", mock_read_text):
            kinds, error = load_registry(Path("/fake/.knowledge"))

        assert kinds == []
        assert "Failed to read registry file" in error
