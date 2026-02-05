"""Tests for atom emitter with v2 format (file_uid, rev_id, fingerprint)."""

from __future__ import annotations

import builtins
import hashlib
import json
from pathlib import Path

import pytest
from spec_manager.refinement.workflows import atom_emitter
from spec_manager.schemas.atoms import LineAtom
from spec_manager.schemas.sections import FileSections, SectionSpan


def _write_file(fs, path: Path, content: str) -> None:
    fs.create_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _make_sections(file_uid: str, spans: list[tuple[int, int, str]]) -> FileSections:
    sections = [
        SectionSpan(
            section_id=f"SEC-{file_uid}-{idx:04d}",
            start_line=start,
            end_line=end,
            label=label,
        )
        for idx, (start, end, label) in enumerate(spans, start=1)
    ]
    total_lines = spans[-1][1] if spans else 0
    return FileSections(file_id=file_uid, sections=sections, total_lines=total_lines)


def test_emit_atoms_normalizes_newlines_and_hashes(fs) -> None:
    """Test that atoms are emitted with correct v2 format including fingerprints."""
    base = Path("/work")
    file_path = base / "specs" / "alpha.txt"
    _write_file(fs, file_path, "line1\r\nline2\rline3\n")

    sections = _make_sections(
        "F0001",
        [
            (1, 2, "INTRO"),
            (3, 3, "DETAILS"),
        ],
    )

    output_path = base / "out" / "atoms.jsonl"
    evidence_path = base / "out" / "evidence.jsonl"

    atoms_emitted = atom_emitter.emit_atoms(
        file_uid="F0001",
        rev_id="R0001",
        file_path=file_path,
        sections=sections,
        output_path=output_path,
        evidence_output=evidence_path,
    )

    assert atoms_emitted == 3

    atoms = _read_jsonl(output_path)
    texts = [atom["text"] for atom in atoms]
    assert texts == ["line1", "line2", "line3"]

    # Check new v2 atom ID format: ATOM-{file_uid}-{rev_id}-L{line:04d}
    assert atoms[0]["atom_id"] == "ATOM-F0001-R0001-L0001"
    assert atoms[1]["atom_id"] == "ATOM-F0001-R0001-L0002"
    assert atoms[2]["atom_id"] == "ATOM-F0001-R0001-L0003"

    # Check new fields
    for atom in atoms:
        assert atom["file_uid"] == "F0001"
        assert atom["rev_id"] == "R0001"
        assert "atom_fingerprint" in atom
        assert len(atom["atom_fingerprint"]) == 64  # SHA-256 hex
        assert "sequence_index" in atom

    # Check sequence_index is 0-based
    assert atoms[0]["sequence_index"] == 0
    assert atoms[1]["sequence_index"] == 1
    assert atoms[2]["sequence_index"] == 2

    expected_hash = hashlib.sha256(b"line1").hexdigest()
    assert atoms[0]["sha256"] == expected_hash

    assert atoms[0]["section_id"] == "SEC-F0001-0001"
    assert atoms[2]["section_id"] == "SEC-F0001-0002"

    for atom in atoms:
        LineAtom.model_validate(atom)

    assert not evidence_path.exists()


def test_emit_atoms_emits_evidence_for_uncovered_lines(fs) -> None:
    """Test that evidence is emitted for lines not covered by sections."""
    base = Path("/work")
    file_path = base / "specs" / "beta.txt"
    _write_file(fs, file_path, "line1\nline2\n")

    sections = _make_sections("F0002", [(1, 1, "INTRO")])
    output_path = base / "out" / "atoms.jsonl"
    evidence_path = base / "out" / "evidence.jsonl"

    atom_emitter.emit_atoms(
        file_uid="F0002",
        rev_id="R0001",
        file_path=file_path,
        sections=sections,
        output_path=output_path,
        evidence_output=evidence_path,
    )

    assert evidence_path.exists()
    evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8").splitlines()[0])
    issues = evidence_payload["details"]["issues"]
    assert any("line 2 not covered" in issue for issue in issues)
    assert any("section_id ''" in issue for issue in issues)
    # Check v2 evidence format has file_uid and rev_id
    assert evidence_payload["details"]["file_uid"] == "F0002"
    assert evidence_payload["details"]["rev_id"] == "R0001"


def test_emit_atoms_emits_evidence_on_count_mismatch(fs, monkeypatch) -> None:
    """Test that evidence is emitted when atom count doesn't match line count."""
    base = Path("/work")
    file_path = base / "specs" / "gamma.txt"
    _write_file(fs, file_path, "line1\nline2\nline3\n")

    sections = _make_sections("F0003", [(1, 3, "ALL")])
    output_path = base / "out" / "atoms.jsonl"
    evidence_path = base / "out" / "evidence.jsonl"

    def _limited_enumerate(iterable, start=0):
        for idx, item in builtins.enumerate(iterable, start=start):
            if idx - start >= 2:
                break
            yield idx, item

    monkeypatch.setattr(atom_emitter, "enumerate", _limited_enumerate)

    atom_emitter.emit_atoms(
        file_uid="F0003",
        rev_id="R0001",
        file_path=file_path,
        sections=sections,
        output_path=output_path,
        evidence_output=evidence_path,
    )

    assert evidence_path.exists()
    evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8").splitlines()[0])
    issues = evidence_payload["details"]["issues"]
    assert any("atom count 2" in issue for issue in issues)


@pytest.mark.parametrize(
    ("content", "expected_atoms"),
    [
        ("", 0),
        ("only line", 1),
        (" \n\t\n", 2),
    ],
)
def test_emit_atoms_edge_cases(fs, content: str, expected_atoms: int) -> None:
    """Test edge cases with empty, single-line, and whitespace content."""
    base = Path("/work")
    file_path = base / "specs" / "edge.txt"
    _write_file(fs, file_path, content)

    if expected_atoms == 0:
        sections = FileSections(file_id="F0004", sections=[], total_lines=0)
    else:
        sections = _make_sections("F0004", [(1, expected_atoms, "EDGE")])

    output_path = base / "out" / "atoms.jsonl"
    evidence_path = base / "out" / "evidence.jsonl"

    atoms_emitted = atom_emitter.emit_atoms(
        file_uid="F0004",
        rev_id="R0001",
        file_path=file_path,
        sections=sections,
        output_path=output_path,
        evidence_output=evidence_path,
    )

    assert atoms_emitted == expected_atoms
    if expected_atoms == 0:
        assert not output_path.exists()
    else:
        atoms = _read_jsonl(output_path)
        assert len(atoms) == expected_atoms
        for atom in atoms:
            LineAtom.model_validate(atom)

    assert not evidence_path.exists()


def test_atom_fingerprint_identical_lines_different_context(fs) -> None:
    """Test that identical lines with different context have different fingerprints."""
    base = Path("/work")
    file_path = base / "specs" / "fingerprint.txt"
    # Create file with duplicate lines but different surrounding context
    _write_file(fs, file_path, "header\nDUPLICATE\nfooter1\nDUPLICATE\nfooter2\n")

    sections = _make_sections("F0005", [(1, 5, "ALL")])
    output_path = base / "out" / "atoms.jsonl"
    evidence_path = base / "out" / "evidence.jsonl"

    atom_emitter.emit_atoms(
        file_uid="F0005",
        rev_id="R0001",
        file_path=file_path,
        sections=sections,
        output_path=output_path,
        evidence_output=evidence_path,
    )

    atoms = _read_jsonl(output_path)

    # Find the two DUPLICATE lines
    duplicate_atoms = [a for a in atoms if a["text"] == "DUPLICATE"]
    assert len(duplicate_atoms) == 2

    # They should have different fingerprints due to different context
    fp1 = duplicate_atoms[0]["atom_fingerprint"]
    fp2 = duplicate_atoms[1]["atom_fingerprint"]
    assert fp1 != fp2


def test_atom_fingerprint_occurrence_index_disambiguates(fs) -> None:
    """Test that occurrence index disambiguates repeated identical contexts."""
    base = Path("/work")
    file_path = base / "specs" / "occurrence.txt"
    # Create file with identical context (all same prev/next)
    _write_file(fs, file_path, "same\nsame\nsame\n")

    sections = _make_sections("F0006", [(1, 3, "ALL")])
    output_path = base / "out" / "atoms.jsonl"
    evidence_path = base / "out" / "evidence.jsonl"

    atom_emitter.emit_atoms(
        file_uid="F0006",
        rev_id="R0001",
        file_path=file_path,
        sections=sections,
        output_path=output_path,
        evidence_output=evidence_path,
    )

    atoms = _read_jsonl(output_path)
    fingerprints = [a["atom_fingerprint"] for a in atoms]

    # All fingerprints should be unique due to occurrence index
    assert len(set(fingerprints)) == 3


def test_emit_atoms_with_different_revisions(fs) -> None:
    """Test that different rev_ids produce different atom IDs."""
    base = Path("/work")
    file_path = base / "specs" / "revisions.txt"
    _write_file(fs, file_path, "content\n")

    sections = _make_sections("F0007", [(1, 1, "ALL")])

    output_r1 = base / "out" / "atoms_r1.jsonl"
    output_r2 = base / "out" / "atoms_r2.jsonl"
    evidence_path = base / "out" / "evidence.jsonl"

    atom_emitter.emit_atoms(
        file_uid="F0007",
        rev_id="R0001",
        file_path=file_path,
        sections=sections,
        output_path=output_r1,
        evidence_output=evidence_path,
    )

    atom_emitter.emit_atoms(
        file_uid="F0007",
        rev_id="R0002",
        file_path=file_path,
        sections=sections,
        output_path=output_r2,
        evidence_output=evidence_path,
    )

    atoms_r1 = _read_jsonl(output_r1)
    atoms_r2 = _read_jsonl(output_r2)

    assert atoms_r1[0]["atom_id"] == "ATOM-F0007-R0001-L0001"
    assert atoms_r2[0]["atom_id"] == "ATOM-F0007-R0002-L0001"

    # Fingerprints should be the same since content/context are same
    assert atoms_r1[0]["atom_fingerprint"] == atoms_r2[0]["atom_fingerprint"]
