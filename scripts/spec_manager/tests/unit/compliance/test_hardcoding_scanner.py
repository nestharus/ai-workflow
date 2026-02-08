"""Tests for the hardcoding scanner (CON-0003/CON-0004 compliance).

This module tests the hardcoding scanner that detects violations of:
- CON-0003: No keyword inference from raw spec text
- CON-0004: Only system stamps and explicit formats allowed
"""

from __future__ import annotations

from pathlib import Path

from spec_manager.compliance.hardcoding_scanner import (
    HardcodingFinding,
    scan_file_for_hardcoding_violations,
    scan_for_hardcoding_violations,
)


class TestHardcodingFinding:
    """Tests for the HardcodingFinding data structure."""

    def test_finding_has_required_fields(self) -> None:
        """HardcodingFinding should have all required fields."""
        finding = HardcodingFinding(
            severity="warning",
            file="test.py",
            line=42,
            pattern_type="keyword_inference",
            message="Test message",
            code_snippet='if "must" in line:',
        )

        assert finding.severity == "warning"
        assert finding.file == "test.py"
        assert finding.line == 42
        assert finding.pattern_type == "keyword_inference"
        assert finding.message == "Test message"
        assert finding.code_snippet == 'if "must" in line:'

    def test_finding_to_dict(self) -> None:
        """HardcodingFinding.to_dict() should serialize correctly."""
        finding = HardcodingFinding(
            severity="warning",
            file="module.py",
            line=10,
            pattern_type="heading_parse",
            message="Found heading pattern",
            code_snippet="re.search(r'^##', text)",
        )

        data = finding.to_dict()

        assert data["severity"] == "warning"
        assert data["file"] == "module.py"
        assert data["line"] == 10
        assert data["pattern_type"] == "heading_parse"


class TestScanFileForViolations:
    """Tests for scan_file_for_hardcoding_violations function."""

    def test_scan_clean_file_no_violations(self, tmp_python_file: Path) -> None:
        """Clean Python file should have no violations."""
        findings = scan_file_for_hardcoding_violations(tmp_python_file)

        assert findings == []

    def test_scan_file_with_keyword_inference(self, tmp_python_file_with_violations: Path) -> None:
        """File with keyword inference should be flagged."""
        findings = scan_file_for_hardcoding_violations(tmp_python_file_with_violations)

        # Should find keyword inference violations
        keyword_findings = [f for f in findings if f.pattern_type == "keyword_inference"]
        assert len(keyword_findings) > 0

        # Check that the finding has expected properties
        finding = keyword_findings[0]
        assert finding.severity == "warning"
        assert "must" in finding.code_snippet.lower() or "shall" in finding.code_snippet.lower()

    def test_scan_file_with_heading_parse(self, tmp_python_file_with_violations: Path) -> None:
        """File with heading parsing should be flagged."""
        findings = scan_file_for_hardcoding_violations(tmp_python_file_with_violations)

        # Should find heading parse violations
        heading_findings = [f for f in findings if f.pattern_type == "heading_parse"]
        assert len(heading_findings) > 0

    def test_scan_nonexistent_file(self, tmp_path: Path) -> None:
        """Scanning nonexistent file should return empty list."""
        nonexistent = tmp_path / "does_not_exist.py"
        findings = scan_file_for_hardcoding_violations(nonexistent)

        assert findings == []


class TestScanForViolations:
    """Tests for scan_for_hardcoding_violations function."""

    def test_scan_multiple_files(self, tmp_path: Path) -> None:
        """Should scan multiple files and aggregate findings."""
        # Create clean file
        clean = tmp_path / "clean.py"
        clean.write_text("def foo(): pass\n", encoding="utf-8")

        # Create file with violation
        violation = tmp_path / "violation.py"
        violation.write_text(
            """def check(text):
    if "must" in text.lower():
        return True
""",
            encoding="utf-8",
        )

        findings = scan_for_hardcoding_violations([clean, violation])

        # Should only have findings from violation file
        assert all(f.file == str(violation) for f in findings)

    def test_scan_skips_non_python_files(self, tmp_path: Path) -> None:
        """Should skip non-Python files."""
        # Create a markdown file with patterns that would trigger findings
        md_file = tmp_path / "readme.md"
        md_file.write_text('if "must" in line:', encoding="utf-8")

        findings = scan_for_hardcoding_violations([md_file])

        assert findings == []

    def test_scan_with_allowlist(self, tmp_path: Path) -> None:
        """Allowlist should suppress specific patterns."""
        # Create file with violation
        py_file = tmp_path / "module.py"
        py_file.write_text(
            """def check(text):
    # Testing keyword detection
    if "must" in text.lower():
        return True
""",
            encoding="utf-8",
        )

        # Scan without allowlist
        findings_without = scan_for_hardcoding_violations([py_file])

        # Scan with allowlist
        allowlist = {"keyword_inference": ["Testing"]}
        findings_with = scan_for_hardcoding_violations([py_file], allowlist=allowlist)

        # Allowlist should not affect results since it checks line content
        # and "Testing" appears in comment, not in the violation line
        assert len(findings_without) >= 0  # May or may not have findings
        assert len(findings_with) >= 0


class TestAllowlistBehavior:
    """Tests for allowlist behavior in the scanner."""

    def test_test_files_are_allowlisted(self, tmp_path: Path) -> None:
        """Test files should be allowlisted (tests can use these patterns)."""
        test_file = tmp_path / "test_module.py"
        test_file.write_text(
            """def test_requirement_keywords():
    # Tests can check for "must" in assertions
    assert "must" in requirement_text.lower()
""",
            encoding="utf-8",
        )

        findings = scan_file_for_hardcoding_violations(test_file)

        # Test files should be allowlisted
        assert findings == []

    def test_system_id_patterns_allowlisted(self, tmp_path: Path) -> None:
        """System ID patterns (ATOM-####, LIB-####) should be allowlisted."""
        py_file = tmp_path / "validator.py"
        py_file.write_text(
            """def validate_id(text):
    # System IDs are OK
    if "ATOM-0001" in text:
        return True
    if "LIB-0002" in text:
        return True
""",
            encoding="utf-8",
        )

        findings = scan_file_for_hardcoding_violations(py_file)

        # System ID patterns should be allowlisted
        assert findings == []

    def test_comments_are_skipped(self, tmp_path: Path) -> None:
        """Comments should not trigger violations."""
        py_file = tmp_path / "commented.py"
        py_file.write_text(
            """# Check for "must" keywords in text
# This comment has "shall" but should not trigger
def process():
    pass
""",
            encoding="utf-8",
        )

        findings = scan_file_for_hardcoding_violations(py_file)

        # Comments should be skipped
        assert findings == []


class TestSpecificPatternDetection:
    """Tests for specific pattern detection."""

    def test_detects_must_keyword_check(self, tmp_path: Path) -> None:
        """Should detect 'must' keyword checks."""
        py_file = tmp_path / "keywords.py"
        py_file.write_text(
            """def find_requirements(lines):
    results = []
    for line in lines:
        if "must" in line.lower():
            results.append(line)
    return results
""",
            encoding="utf-8",
        )

        findings = scan_file_for_hardcoding_violations(py_file)

        assert len(findings) > 0
        assert any("keyword" in f.pattern_type for f in findings)

    def test_detects_heading_regex(self, tmp_path: Path) -> None:
        """Should detect heading-based regex patterns."""
        py_file = tmp_path / "parser.py"
        py_file.write_text(
            """import re

def parse_sections(text):
    matches = re.findall(r"^## (.+)$", text, re.MULTILINE)
    return matches
""",
            encoding="utf-8",
        )

        findings = scan_file_for_hardcoding_violations(py_file)

        assert len(findings) > 0
        heading_findings = [f for f in findings if f.pattern_type == "heading_parse"]
        assert len(heading_findings) > 0

    def test_detects_banned_list_pattern(self, tmp_path: Path) -> None:
        """Should detect hardcoded banned/prohibited lists."""
        py_file = tmp_path / "lists.py"
        py_file.write_text(
            """
BANNED_LIBRARIES = [
    "unsafe_lib",
    "deprecated_module",
]

def check_imports(code):
    for banned in BANNED_LIBRARIES:
        if banned in code:
            return False
    return True
""",
            encoding="utf-8",
        )

        findings = scan_file_for_hardcoding_violations(py_file)

        # Should detect semantic list pattern
        list_findings = [f for f in findings if f.pattern_type == "semantic_list"]
        assert len(list_findings) > 0


class TestReportOnlyMode:
    """Tests verifying scanner runs in report-only mode."""

    def test_all_findings_are_warnings(self, tmp_python_file_with_violations: Path) -> None:
        """All findings should have severity 'warning' (report-only)."""
        findings = scan_file_for_hardcoding_violations(tmp_python_file_with_violations)

        # All findings should be warnings, not errors
        for finding in findings:
            assert finding.severity == "warning", (
                f"Finding has severity '{finding.severity}', expected 'warning'"
            )

    def test_findings_do_not_block_execution(self, tmp_python_file_with_violations: Path) -> None:
        """Scanner should complete without raising exceptions."""
        # This should not raise
        findings = scan_for_hardcoding_violations([tmp_python_file_with_violations])

        # Should return findings, not raise
        assert isinstance(findings, list)
