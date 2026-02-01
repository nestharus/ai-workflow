from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.spec_refinement.workflows.section_validator import validate_sections


def _write_sections(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_validate_sections_valid_coverage(fs) -> None:
    base = Path("/work")
    sections_path = base / "manifest" / "F0001.sections.json"
    evidence_path = base / "evidence" / "F0001.jsonl"

    payload = {
        "file_id": "F0001",
        "sections": [
            {
                "section_id": "SEC-F0001-0001",
                "start_line": 1,
                "end_line": 2,
                "label": "INTRO",
            }
        ],
        "total_lines": 2,
    }
    _write_sections(sections_path, payload)

    result = validate_sections(
        file_id="F0001",
        sections_path=sections_path,
        total_lines=2,
        evidence_output=evidence_path,
    )

    assert result == {"valid": True, "issues": [], "evidence_count": 0}
    assert not evidence_path.exists()


def test_validate_sections_gap_detection(fs) -> None:
    base = Path("/work")
    sections_path = base / "manifest" / "F0002.sections.json"
    evidence_path = base / "evidence" / "F0002.jsonl"

    payload = {
        "file_id": "F0002",
        "sections": [
            {
                "section_id": "SEC-F0002-0001",
                "start_line": 1,
                "end_line": 2,
                "label": "INTRO",
            }
        ],
        "total_lines": 4,
    }
    _write_sections(sections_path, payload)

    result = validate_sections(
        file_id="F0002",
        sections_path=sections_path,
        total_lines=4,
        evidence_output=evidence_path,
    )

    assert result["valid"] is False
    assert any("do not cover all lines" in issue for issue in result["issues"])
    assert result["evidence_count"] == 1
    assert evidence_path.exists()


def test_validate_sections_overlap_detection(fs) -> None:
    base = Path("/work")
    sections_path = base / "manifest" / "F0003.sections.json"
    evidence_path = base / "evidence" / "F0003.jsonl"

    payload = {
        "file_id": "F0003",
        "sections": [
            {
                "section_id": "SEC-F0003-0001",
                "start_line": 1,
                "end_line": 3,
                "label": "INTRO",
            },
            {
                "section_id": "SEC-F0003-0002",
                "start_line": 3,
                "end_line": 4,
                "label": "DETAILS",
            },
        ],
        "total_lines": 4,
    }
    _write_sections(sections_path, payload)

    result = validate_sections(
        file_id="F0003",
        sections_path=sections_path,
        total_lines=4,
        evidence_output=evidence_path,
    )

    assert result["valid"] is False
    assert any(
        "start_line" in issue or "do not cover all lines" in issue for issue in result["issues"]
    )
    assert evidence_path.exists()


def test_validate_sections_section_id_format(fs) -> None:
    base = Path("/work")
    sections_path = base / "manifest" / "F0004.sections.json"
    evidence_path = base / "evidence" / "F0004.jsonl"

    payload = {
        "file_id": "F0004",
        "sections": [
            {
                "section_id": "SEC-F0004-01",
                "start_line": 1,
                "end_line": 2,
                "label": "INTRO",
            }
        ],
        "total_lines": 2,
    }
    _write_sections(sections_path, payload)

    result = validate_sections(
        file_id="F0004",
        sections_path=sections_path,
        total_lines=2,
        evidence_output=evidence_path,
    )

    assert result["valid"] is False
    assert any("format" in issue for issue in result["issues"])
    assert evidence_path.exists()


@pytest.mark.parametrize("section_id", ["SEC-F0005-0002", "SEC-F0005-9999"])
def test_validate_sections_ordinal_sequence(fs, section_id: str) -> None:
    base = Path("/work")
    sections_path = base / "manifest" / "F0005.sections.json"
    evidence_path = base / "evidence" / "F0005.jsonl"

    payload = {
        "file_id": "F0005",
        "sections": [
            {
                "section_id": section_id,
                "start_line": 1,
                "end_line": 1,
                "label": "INTRO",
            }
        ],
        "total_lines": 1,
    }
    _write_sections(sections_path, payload)

    result = validate_sections(
        file_id="F0005",
        sections_path=sections_path,
        total_lines=1,
        evidence_output=evidence_path,
    )

    assert result["valid"] is False
    assert any("expected ordinal" in issue for issue in result["issues"])
    assert evidence_path.exists()


def test_validate_sections_schema_validation_error(fs) -> None:
    base = Path("/work")
    sections_path = base / "manifest" / "F0006.sections.json"
    evidence_path = base / "evidence" / "F0006.jsonl"

    sections_path.parent.mkdir(parents=True, exist_ok=True)
    sections_path.write_text("{", encoding="utf-8")

    result = validate_sections(
        file_id="F0006",
        sections_path=sections_path,
        total_lines=1,
        evidence_output=evidence_path,
    )

    assert result["valid"] is False
    assert any("Failed to parse sections file" in issue for issue in result["issues"])
    assert evidence_path.exists()


def test_validate_sections_total_lines_mismatch(fs) -> None:
    base = Path("/work")
    sections_path = base / "manifest" / "F0007.sections.json"
    evidence_path = base / "evidence" / "F0007.jsonl"

    payload = {
        "file_id": "F0007",
        "sections": [
            {
                "section_id": "SEC-F0007-0001",
                "start_line": 1,
                "end_line": 3,
                "label": "INTRO",
            }
        ],
        "total_lines": 2,
    }
    _write_sections(sections_path, payload)

    result = validate_sections(
        file_id="F0007",
        sections_path=sections_path,
        total_lines=2,
        evidence_output=evidence_path,
    )

    assert result["valid"] is False
    assert any("exceeds total_lines" in issue for issue in result["issues"])
    assert evidence_path.exists()
