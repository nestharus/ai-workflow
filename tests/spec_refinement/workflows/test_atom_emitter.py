from __future__ import annotations

import builtins
import hashlib
import json
from pathlib import Path

import pytest

from scripts.spec_refinement.schemas.atoms import LineAtom
from scripts.spec_refinement.schemas.sections import FileSections, SectionSpan
from scripts.spec_refinement.workflows import atom_emitter


def _write_file(fs, path: Path, content: str) -> None:
    fs.create_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _make_sections(file_id: str, spans: list[tuple[int, int, str]]) -> FileSections:
    sections = [
        SectionSpan(
            section_id=f"SEC-{file_id}-{idx:04d}",
            start_line=start,
            end_line=end,
            label=label,
        )
        for idx, (start, end, label) in enumerate(spans, start=1)
    ]
    total_lines = spans[-1][1] if spans else 0
    return FileSections(file_id=file_id, sections=sections, total_lines=total_lines)


def test_emit_atoms_normalizes_newlines_and_hashes(fs) -> None:
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
        file_id="F0001",
        file_path=file_path,
        sections=sections,
        output_path=output_path,
        evidence_output=evidence_path,
    )

    assert atoms_emitted == 3

    atoms = _read_jsonl(output_path)
    texts = [atom["text"] for atom in atoms]
    assert texts == ["line1", "line2", "line3"]

    assert atoms[0]["atom_id"] == "ATOM-F0001-L0001"
    assert atoms[1]["atom_id"] == "ATOM-F0001-L0002"
    assert atoms[2]["atom_id"] == "ATOM-F0001-L0003"

    expected_hash = hashlib.sha256(b"line1").hexdigest()
    assert atoms[0]["sha256"] == expected_hash

    assert atoms[0]["section_id"] == "SEC-F0001-0001"
    assert atoms[2]["section_id"] == "SEC-F0001-0002"

    for atom in atoms:
        LineAtom.model_validate(atom)

    assert not evidence_path.exists()


def test_emit_atoms_emits_evidence_for_uncovered_lines(fs) -> None:
    base = Path("/work")
    file_path = base / "specs" / "beta.txt"
    _write_file(fs, file_path, "line1\nline2\n")

    sections = _make_sections("F0002", [(1, 1, "INTRO")])
    output_path = base / "out" / "atoms.jsonl"
    evidence_path = base / "out" / "evidence.jsonl"

    atom_emitter.emit_atoms(
        file_id="F0002",
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


def test_emit_atoms_emits_evidence_on_count_mismatch(fs, monkeypatch) -> None:
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
        file_id="F0003",
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
        file_id="F0004",
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
