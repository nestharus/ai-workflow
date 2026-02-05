r"""Newline handling and atom fingerprinting.

All input files are normalized to LF (\n) newlines before processing to ensure
deterministic line-atom generation across platforms. This means:

1. CRLF (\r\n) -> LF (\n)
2. CR (\r) -> LF (\n)
3. LF (\n) -> LF (\n) (unchanged)

Line splitting uses str.splitlines(keepends=False) after normalization.
SHA-256 hashes are computed on the normalized line text (UTF-8 encoded).

Atom fingerprints (ALG-CORE-0004) enable cross-revision matching by combining:
- Normalized line content
- Previous non-blank line content
- Next non-blank line content
- Occurrence index for duplicate disambiguation

Phase 3 additions:
- Evidence ranges are built alongside atoms (ALG-EVID-0002)
- emit_atoms_with_evidence returns both atoms and evidence ranges
"""

from __future__ import annotations

import hashlib
import json
from builtins import enumerate
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.refinement.core.gap import GapEvidence
from spec_manager.schemas.atoms import LineAtom
from spec_manager.schemas.evidence_ranges import EvidenceRange, EvidenceRangesArtifact
from spec_manager.schemas.sections import FileSections, SectionSpan


def emit_atoms(
    file_uid: str,
    rev_id: str,
    file_path: Path,
    sections: FileSections,
    output_path: Path,
    evidence_output: Path,
) -> int:
    """Emit deterministic line-atoms for a file with fingerprints.

    Newline handling: All newlines (LF, CRLF, CR) are normalized to LF
    before line splitting to ensure deterministic atom generation across
    platforms.

    Args:
        file_uid: File UID (F####)
        rev_id: Revision ID (R####)
        file_path: Path to the source file
        sections: Section spans for the file
        output_path: Path to write atoms JSONL
        evidence_output: Path to write gap evidence JSONL

    Returns:
        Total number of atoms emitted.
    """
    raw_bytes = _read_snapshot_bytes(file_path)
    content = raw_bytes.decode("utf-8")
    normalized = _normalize_newlines(content)
    lines = normalized.splitlines(keepends=False)

    section_ids = {section.section_id for section in sections.sections}
    issues: list[str] = []
    section_index = 0
    atoms_emitted = 0

    # Precompute next non-blank indices for fingerprint calculation
    nonblank_next_cache = _compute_next_nonblank(lines)

    # Track occurrences for fingerprint disambiguation
    occurrence_counter: Counter[str] = Counter()
    nonblank_prev: str | None = None

    for idx, text in enumerate(lines):
        line_no = idx + 1

        section_id, section_index = _resolve_section_id(
            line_no=line_no,
            sections=sections.sections,
            start_index=section_index,
        )
        if section_id is None:
            section_id = ""
            issues.append(f"line {line_no} not covered by any section span")
        if section_id not in section_ids:
            issues.append(
                f"line {line_no} section_id {section_id!r} not found in sections manifest"
            )

        # Normalize text for fingerprint
        normalized_text = _normalize_for_fingerprint(text)
        occurrence_index = occurrence_counter[normalized_text]
        occurrence_counter[normalized_text] += 1

        # Build fingerprint (ALG-CORE-0004)
        next_nonblank = nonblank_next_cache[idx]
        fingerprint = _build_atom_fingerprint(
            content=text,
            prev_nonblank=nonblank_prev,
            next_nonblank=next_nonblank,
            occurrence_index=occurrence_index,
        )

        # Update prev_nonblank tracker
        if text.strip():
            nonblank_prev = text

        sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        atom_id = f"ATOM-{file_uid}-{rev_id}-L{line_no:04d}"

        atom_payload = {
            "atom_id": atom_id,
            "atom_fingerprint": fingerprint,
            "file_uid": file_uid,
            "rev_id": rev_id,
            "line_no": line_no,
            "sequence_index": idx,
            "section_id": section_id,
            "sha256": sha256,
            "text": text,
        }
        atom = LineAtom.model_validate(atom_payload)
        _append_jsonl(output_path, atom.model_dump())
        atoms_emitted += 1

    if atoms_emitted != len(lines):
        issues.append(f"atom count {atoms_emitted} does not match line count {len(lines)}")

    if issues:
        evidence = GapEvidence(
            invariant_family="coverage",
            description="Atom emission validation failed",
            details={
                "file_uid": file_uid,
                "rev_id": rev_id,
                "issues": issues,
                "file_path": str(file_path),
            },
            confidence=1.0,
            location=str(file_path),
            detector="atom-emitter",
        )
        _emit_evidence(evidence, evidence_output)

    return atoms_emitted


def _read_snapshot_bytes(path: Path) -> bytes:
    """Read file contents as bytes."""
    chunks: list[bytes] = []
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            chunks.append(chunk)
    return b"".join(chunks)


def _normalize_newlines(text: str) -> str:
    """Normalize all newlines to LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_for_fingerprint(text: str) -> str:
    """Normalize text for fingerprint calculation.

    Strips leading/trailing whitespace and collapses internal whitespace
    for more robust fingerprint matching across formatting changes.
    """
    return " ".join(text.split())


def _compute_next_nonblank(lines: list[str]) -> list[str | None]:
    """Precompute next non-blank line for each position.

    Returns:
        List where index i contains the next non-blank line after position i,
        or None if no non-blank line follows.
    """
    result: list[str | None] = [None] * len(lines)
    next_nonblank: str | None = None

    for i in range(len(lines) - 1, -1, -1):
        result[i] = next_nonblank
        if lines[i].strip():
            next_nonblank = lines[i]

    return result


def _build_atom_fingerprint(
    content: str,
    prev_nonblank: str | None,
    next_nonblank: str | None,
    occurrence_index: int,
) -> str:
    """Build atom fingerprint for cross-revision matching (ALG-CORE-0004).

    The fingerprint combines:
    - Normalized line content
    - Previous non-blank line (provides context)
    - Next non-blank line (provides context)
    - Occurrence index (disambiguates duplicate lines)

    Args:
        content: Line text
        prev_nonblank: Previous non-blank line text, or None
        next_nonblank: Next non-blank line text, or None
        occurrence_index: Index of this occurrence of the normalized content

    Returns:
        64-character hex fingerprint (SHA-256)
    """
    normalized = _normalize_for_fingerprint(content)
    prev = _normalize_for_fingerprint(prev_nonblank or "")
    next_ = _normalize_for_fingerprint(next_nonblank or "")

    # Join with separator that won't appear in normalized content
    payload = "\n---\n".join([prev, normalized, next_, str(occurrence_index)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolve_section_id(
    *,
    line_no: int,
    sections: list[SectionSpan],
    start_index: int,
) -> tuple[str | None, int]:
    """Resolve section ID for a line number."""
    index = start_index
    while index < len(sections):
        span = sections[index]
        if line_no < span.start_line:
            return None, index
        if span.start_line <= line_no <= span.end_line:
            return span.section_id, index
        index += 1
    return None, index


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Append a JSON object to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def _emit_evidence(evidence: GapEvidence, output_path: Path) -> None:
    """Append evidence record to JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence.to_dict(), sort_keys=True) + "\n")


@dataclass
class AtomEmissionResult:
    """Result of atom emission with evidence ranges.

    Attributes:
        atoms: List of emitted atoms
        evidence_ranges: List of evidence ranges built from sections
        uncovered_atom_ids: List of atom IDs not covered by any section
        atoms_emitted: Count of atoms emitted
    """

    atoms: list[LineAtom]
    evidence_ranges: list[EvidenceRange]
    uncovered_atom_ids: list[str]
    atoms_emitted: int


def emit_atoms_with_evidence(
    file_uid: str,
    rev_id: str,
    file_path: Path,
    sections: FileSections,
    output_path: Path | None = None,
    evidence_output: Path | None = None,
    evidence_ranges_output: Path | None = None,
) -> AtomEmissionResult:
    """Emit deterministic line-atoms with evidence ranges (Phase 3).

    This extends emit_atoms to also build evidence ranges per ALG-EVID-0002,
    enabling full atom accounting per INV-ACC-0101.

    Args:
        file_uid: File UID (F####)
        rev_id: Revision ID (R####)
        file_path: Path to the source file
        sections: Section spans for the file
        output_path: Optional path to write atoms JSONL
        evidence_output: Optional path to write gap evidence JSONL
        evidence_ranges_output: Optional path to write evidence ranges JSON

    Returns:
        AtomEmissionResult containing atoms, evidence ranges, and coverage info
    """
    raw_bytes = _read_snapshot_bytes(file_path)
    content = raw_bytes.decode("utf-8")
    normalized = _normalize_newlines(content)
    lines = normalized.splitlines(keepends=False)

    section_ids = {section.section_id for section in sections.sections}
    issues: list[str] = []
    section_index = 0

    # Precompute next non-blank indices for fingerprint calculation
    nonblank_next_cache = _compute_next_nonblank(lines)

    # Track occurrences for fingerprint disambiguation
    occurrence_counter: Counter[str] = Counter()
    nonblank_prev: str | None = None

    atoms: list[LineAtom] = []
    atom_by_line: dict[int, LineAtom] = {}

    for idx, text in enumerate(lines):
        line_no = idx + 1

        section_id, section_index = _resolve_section_id(
            line_no=line_no,
            sections=sections.sections,
            start_index=section_index,
        )
        if section_id is None:
            section_id = ""
            issues.append(f"line {line_no} not covered by any section span")
        if section_id not in section_ids:
            issues.append(
                f"line {line_no} section_id {section_id!r} not found in sections manifest"
            )

        # Normalize text for fingerprint
        normalized_text = _normalize_for_fingerprint(text)
        occurrence_index = occurrence_counter[normalized_text]
        occurrence_counter[normalized_text] += 1

        # Build fingerprint (ALG-CORE-0004)
        next_nonblank = nonblank_next_cache[idx]
        fingerprint = _build_atom_fingerprint(
            content=text,
            prev_nonblank=nonblank_prev,
            next_nonblank=next_nonblank,
            occurrence_index=occurrence_index,
        )

        # Update prev_nonblank tracker
        if text.strip():
            nonblank_prev = text

        sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        atom_id = f"ATOM-{file_uid}-{rev_id}-L{line_no:04d}"

        atom_payload = {
            "atom_id": atom_id,
            "atom_fingerprint": fingerprint,
            "file_uid": file_uid,
            "rev_id": rev_id,
            "line_no": line_no,
            "sequence_index": idx,
            "section_id": section_id,
            "sha256": sha256,
            "text": text,
        }
        atom = LineAtom.model_validate(atom_payload)
        atoms.append(atom)
        atom_by_line[line_no] = atom

        if output_path:
            _append_jsonl(output_path, atom.model_dump())

    # Build evidence ranges from sections
    evidence_ranges: list[EvidenceRange] = []
    all_atom_ids = {a.atom_id for a in atoms}
    covered_atom_ids: set[str] = set()

    for span in sections.sections:
        evidence_id = f"EVID-{file_uid}-{rev_id}-L{span.start_line}-L{span.end_line}"

        span_atom_ids: list[str] = []
        for line_no in range(span.start_line, span.end_line + 1):
            if line_no in atom_by_line:
                atom = atom_by_line[line_no]
                span_atom_ids.append(atom.atom_id)
                covered_atom_ids.add(atom.atom_id)

        evidence_ranges.append(
            EvidenceRange(
                evidence_id=evidence_id,
                file_uid=file_uid,
                rev_id=rev_id,
                start_line=span.start_line,
                end_line=span.end_line,
                atom_ids=span_atom_ids,
                section_id=span.section_id,
                label=span.label,
            )
        )

    uncovered_atom_ids = sorted(all_atom_ids - covered_atom_ids)

    # Write evidence ranges artifact if path provided
    if evidence_ranges_output:
        artifact = EvidenceRangesArtifact(
            file_uid=file_uid,
            rev_id=rev_id,
            ranges=evidence_ranges,
            uncovered_atoms=uncovered_atom_ids,
        )
        evidence_ranges_output.parent.mkdir(parents=True, exist_ok=True)
        with evidence_ranges_output.open("w", encoding="utf-8") as handle:
            handle.write(artifact.model_dump_json(indent=2))

    if len(atoms) != len(lines):
        issues.append(f"atom count {len(atoms)} does not match line count {len(lines)}")

    if issues and evidence_output:
        evidence = GapEvidence(
            invariant_family="coverage",
            description="Atom emission validation failed",
            details={
                "file_uid": file_uid,
                "rev_id": rev_id,
                "issues": issues,
                "file_path": str(file_path),
            },
            confidence=1.0,
            location=str(file_path),
            detector="atom-emitter",
        )
        _emit_evidence(evidence, evidence_output)

    return AtomEmissionResult(
        atoms=atoms,
        evidence_ranges=evidence_ranges,
        uncovered_atom_ids=uncovered_atom_ids,
        atoms_emitted=len(atoms),
    )
