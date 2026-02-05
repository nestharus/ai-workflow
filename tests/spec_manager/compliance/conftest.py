"""Shared fixtures for compliance tests.

This module provides test fixtures for:
- Schema registry instances
- Sample valid/invalid artifacts
- Mock atom manifests with known coverage states
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from spec_manager.compliance.schema_registry import SchemaRegistry
from spec_manager.core.coverage import CoverageTracker, FragmentStatus


@pytest.fixture
def schema_registry() -> SchemaRegistry:
    """Provide a fresh SchemaRegistry instance for each test."""
    return SchemaRegistry()


@pytest.fixture
def valid_atoms_manifest() -> dict[str, Any]:
    """Provide a valid atoms manifest that passes schema validation."""
    return {
        "file_uid": "F0001",
        "rev_id": "rev_001",
        "atoms": [
            {
                "atom_id": "ATOM-0001",
                "line_no": 1,
                "content": "This is the first atom content.",
            },
            {
                "atom_id": "ATOM-0002",
                "line_no": 5,
                "content": "This is the second atom content.",
            },
        ],
    }


@pytest.fixture
def invalid_atoms_manifest_missing_required() -> dict[str, Any]:
    """Provide an atoms manifest missing required fields."""
    return {
        "file_uid": "F0001",
        # Missing 'rev_id' and 'atoms'
    }


@pytest.fixture
def invalid_atoms_manifest_bad_atom() -> dict[str, Any]:
    """Provide an atoms manifest with invalid atom entry."""
    return {
        "file_uid": "F0001",
        "rev_id": "rev_001",
        "atoms": [
            {
                "atom_id": "ATOM-0001",
                # Missing required 'line_no' and 'content'
            },
        ],
    }


@pytest.fixture
def valid_derived_elements() -> dict[str, Any]:
    """Provide valid derived elements output that passes schema validation."""
    return {
        "elements": [
            {
                "elem_id": "ELEM-0001",
                "kind": "requirement",
                "lib_id": "LIB-0001",
                "title": "Sample Requirement",
                "evidence_atom_ids": ["ATOM-0001", "ATOM-0002"],
                "status": "active",
            },
        ],
    }


@pytest.fixture
def invalid_derived_elements_missing_fields() -> dict[str, Any]:
    """Provide derived elements with missing required fields."""
    return {
        "elements": [
            {
                "elem_id": "ELEM-0001",
                # Missing required 'kind', 'lib_id', 'title', 'evidence_atom_ids', 'status'
            },
        ],
    }


@pytest.fixture
def coverage_tracker_all_projected() -> CoverageTracker:
    """Provide a coverage tracker where all atoms are projected (mapped).

    Represents CON-0002 scenario: all_mapped
    """
    tracker = CoverageTracker()
    content = "Line 1: First atom.\nLine 2: Second atom.\nLine 3: Third atom."
    root = tracker.initialize("test.md", content)

    # Split into three fragments
    children = tracker.split(root.id, [20, 40])

    # Project all fragments
    for child in children:
        tracker.project(child.id, "requirement", f"Projected: {child.content}")

    return tracker


@pytest.fixture
def coverage_tracker_some_remainder() -> CoverageTracker:
    """Provide a coverage tracker with some atoms in remainder (not yet processed).

    Represents CON-0002 scenario: some_remainder
    """
    tracker = CoverageTracker()
    content = "Line 1: First atom.\nLine 2: Second atom.\nLine 3: Third atom."
    root = tracker.initialize("test.md", content)

    # Split into three fragments
    children = tracker.split(root.id, [20, 40])

    # Project only the first fragment, leave others as prose (remainder)
    tracker.project(children[0].id, "requirement", f"Projected: {children[0].content}")
    # children[1] and children[2] remain as PROSE (in remainder queue)

    return tracker


@pytest.fixture
def coverage_tracker_some_excluded() -> CoverageTracker:
    """Provide a coverage tracker with some atoms marked as noise (excluded).

    Represents CON-0002 scenario: some_excluded
    """
    tracker = CoverageTracker()
    content = "Line 1: First atom.\nLine 2: Second atom.\nLine 3: Noise content."
    root = tracker.initialize("test.md", content)

    # Split into three fragments
    children = tracker.split(root.id, [20, 40])

    # Project first two, mark last as noise (excluded)
    tracker.project(children[0].id, "requirement", f"Projected: {children[0].content}")
    tracker.project(children[1].id, "constraint", f"Projected: {children[1].content}")
    tracker.mark_as_noise(children[2].id, "Self-justifying content, adds nothing")

    return tracker


@pytest.fixture
def sample_valid_artifact_for_quarantine() -> dict[str, Any]:
    """Provide a valid artifact for quarantine testing."""
    return {
        "elements": [
            {
                "elem_id": "ELEM-0001",
                "kind": "requirement",
                "lib_id": "LIB-0001",
                "title": "Valid Requirement",
                "evidence_atom_ids": ["ATOM-0001"],
                "status": "active",
            },
        ],
    }


@pytest.fixture
def sample_invalid_artifact_for_quarantine() -> dict[str, Any]:
    """Provide an invalid artifact that should be quarantined."""
    return {
        "elements": [
            {
                "missing_required_field": True,
                # Missing all required fields
            },
        ],
    }


@pytest.fixture
def atom_manifest_all_mapped() -> dict[str, Any]:
    """Atom manifest fixture for CON-0002 testing: all atoms mapped.

    All atoms have been mapped to derived elements.
    """
    return {
        "atoms": [
            {"atom_id": "ATOM-0001", "status": "mapped", "mapped_to": "ELEM-0001"},
            {"atom_id": "ATOM-0002", "status": "mapped", "mapped_to": "ELEM-0002"},
            {"atom_id": "ATOM-0003", "status": "mapped", "mapped_to": "ELEM-0001"},
        ],
        "coverage_summary": {
            "total": 3,
            "mapped": 3,
            "remainder": 0,
            "excluded": 0,
        },
    }


@pytest.fixture
def atom_manifest_some_remainder() -> dict[str, Any]:
    """Atom manifest fixture for CON-0002 testing: some atoms in remainder.

    Some atoms have not been mapped yet.
    """
    return {
        "atoms": [
            {"atom_id": "ATOM-0001", "status": "mapped", "mapped_to": "ELEM-0001"},
            {"atom_id": "ATOM-0002", "status": "remainder", "mapped_to": None},
            {"atom_id": "ATOM-0003", "status": "remainder", "mapped_to": None},
        ],
        "coverage_summary": {
            "total": 3,
            "mapped": 1,
            "remainder": 2,
            "excluded": 0,
        },
    }


@pytest.fixture
def atom_manifest_some_excluded() -> dict[str, Any]:
    """Atom manifest fixture for CON-0002 testing: some atoms excluded.

    Some atoms have been explicitly excluded (noise).
    """
    return {
        "atoms": [
            {"atom_id": "ATOM-0001", "status": "mapped", "mapped_to": "ELEM-0001"},
            {"atom_id": "ATOM-0002", "status": "mapped", "mapped_to": "ELEM-0002"},
            {"atom_id": "ATOM-0003", "status": "excluded", "reason": "noise"},
        ],
        "coverage_summary": {
            "total": 3,
            "mapped": 2,
            "remainder": 0,
            "excluded": 1,
        },
    }


@pytest.fixture
def tmp_python_file(tmp_path: Path) -> Path:
    """Create a temporary Python file for hardcoding scanner tests."""
    py_file = tmp_path / "test_module.py"
    # Use raw string (r-prefix) to preserve backslashes
    py_file.write_text(
        r'''"""Test module for hardcoding scanner."""

def process_spec(text: str) -> list[str]:
    """Process specification text."""
    # This is fine - using structured data
    return text.split("\n")
''',
        encoding="utf-8",
    )
    return py_file


@pytest.fixture
def tmp_python_file_with_violations(tmp_path: Path) -> Path:
    """Create a temporary Python file with hardcoding violations."""
    py_file = tmp_path / "violations.py"
    # Use raw string (r-prefix) to preserve backslashes
    py_file.write_text(
        r'''"""Module with hardcoding violations."""
import re

def infer_requirements(text: str) -> list[str]:
    """Infer requirements from text - VIOLATION: keyword inference."""
    # Violation: scanning for "must" to infer requirements
    requirements = []
    for line in text.split("\n"):
        if "must" in line.lower() or "shall" in line.lower():
            requirements.append(line)
    return requirements

def parse_sections(text: str) -> dict:
    """Parse sections from text - VIOLATION: heading-based parsing."""
    # Violation: regex matching on markdown headings
    sections = {}
    matches = re.findall(r"^##\s+(.+)$", text, re.MULTILINE)
    for match in matches:
        sections[match] = []
    return sections
''',
        encoding="utf-8",
    )
    return py_file
