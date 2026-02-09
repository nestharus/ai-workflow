"""Shared fixtures for integration compliance tests.

Mirrors the fixtures from unit/compliance/conftest.py that integration
tests also depend on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from spec_manager.compliance.schema_registry import SchemaRegistry
from spec_manager.core.coverage import CoverageTracker


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
            },
        ],
    }


@pytest.fixture
def coverage_tracker_all_projected() -> CoverageTracker:
    """Provide a coverage tracker where all atoms are projected (mapped)."""
    tracker = CoverageTracker()
    content = "Line 1: First atom.\nLine 2: Second atom.\nLine 3: Third atom."
    root = tracker.initialize("test.md", content)

    children = tracker.split(root.id, [20, 40])

    for child in children:
        tracker.project(child.id, "requirement", f"Projected: {child.content}")

    return tracker


@pytest.fixture
def coverage_tracker_some_remainder() -> CoverageTracker:
    """Provide a coverage tracker with some atoms in remainder (not yet processed)."""
    tracker = CoverageTracker()
    content = "Line 1: First atom.\nLine 2: Second atom.\nLine 3: Third atom."
    root = tracker.initialize("test.md", content)

    children = tracker.split(root.id, [20, 40])

    tracker.project(children[0].id, "requirement", f"Projected: {children[0].content}")

    return tracker


@pytest.fixture
def coverage_tracker_some_excluded() -> CoverageTracker:
    """Provide a coverage tracker with some atoms marked as noise (excluded)."""
    tracker = CoverageTracker()
    content = "Line 1: First atom.\nLine 2: Second atom.\nLine 3: Noise content."
    root = tracker.initialize("test.md", content)

    children = tracker.split(root.id, [20, 40])

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
            },
        ],
    }


@pytest.fixture
def tmp_python_file(tmp_path: Path) -> Path:
    """Create a temporary Python file for hardcoding scanner tests."""
    py_file = tmp_path / "test_module.py"
    py_file.write_text(
        r'''"""Test module for hardcoding scanner."""

def process_spec(text: str) -> list[str]:
    """Process specification text."""
    return text.split("\n")
''',
        encoding="utf-8",
    )
    return py_file


@pytest.fixture
def tmp_python_file_with_violations(tmp_path: Path) -> Path:
    """Create a temporary Python file with hardcoding violations."""
    py_file = tmp_path / "violations.py"
    py_file.write_text(
        r'''"""Module with hardcoding violations."""
import re

def infer_requirements(text: str) -> list[str]:
    """Infer requirements from text - VIOLATION: keyword inference."""
    requirements = []
    for line in text.split("\n"):
        if "must" in line.lower() or "shall" in line.lower():
            requirements.append(line)
    return requirements

def parse_sections(text: str) -> dict:
    """Parse sections from text - VIOLATION: heading-based parsing."""
    sections = {}
    matches = re.findall(r"^##\s+(.+)$", text, re.MULTILINE)
    for match in matches:
        sections[match] = []
    return sections
''',
        encoding="utf-8",
    )
    return py_file
