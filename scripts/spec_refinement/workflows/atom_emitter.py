r"""Newline handling.

All input files are normalized to LF (\n) newlines before processing to ensure
deterministic line-atom generation across platforms. This means:

1. CRLF (\r\n) → LF (\n)
2. CR (\r) → LF (\n)
3. LF (\n) → LF (\n) (unchanged)

Line splitting uses str.splitlines(keepends=False) after normalization.
SHA-256 hashes are computed on the normalized line text (UTF-8 encoded).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.spec_manager.spec_manager.schemas.atoms import LineAtom
from scripts.spec_manager.spec_manager.schemas.sections import FileSections, SectionSpan
from scripts.spec_refinement.core.gap import GapEvidence


def emit_atoms(
    file_id: str,
    file_path: Path,
    sections: FileSections,
    output_path: Path,
    evidence_output: Path,
) -> int:
    """Emit deterministic line-atoms for a file.

    Newline handling: All newlines (LF, CRLF, CR) are normalized to LF
    before line splitting to ensure deterministic atom generation across
    platforms.

    Returns: Total number of atoms emitted.
    """
    raw_bytes = _read_snapshot_bytes(file_path)
    content = raw_bytes.decode("utf-8")
    normalized = _normalize_newlines(content)
    lines = normalized.splitlines(keepends=False)

    section_ids = {section.section_id for section in sections.sections}
    issues: list[str] = []
    section_index = 0
    atoms_emitted = 0
    for line_no, text in enumerate(lines, start=1):
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

        sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        atom_id = f"ATOM-{file_id}-L{line_no:04d}"
        atom_payload = {
            "atom_id": atom_id,
            "line_no": line_no,
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
                "file_id": file_id,
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
    chunks: list[bytes] = []
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            chunks.append(chunk)
    return b"".join(chunks)


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _resolve_section_id(
    *,
    line_no: int,
    sections: list[SectionSpan],
    start_index: int,
) -> tuple[str | None, int]:
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def _emit_evidence(evidence: GapEvidence, output_path: Path) -> None:
    """Append evidence record to JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence.to_dict(), sort_keys=True) + "\n")
