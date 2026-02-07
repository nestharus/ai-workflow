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

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from spec_manager.core.gap import GapEvidence
from spec_manager.schemas.atoms import LineAtom
from spec_manager.schemas.files import FilesManifest
from spec_manager.schemas.sections import FileSections
from spec_manager.schemas.terms import FileTerms


def validate_files_manifest(
    manifest_path: Path,
    evidence_output: Path,
) -> dict[str, Any]:
    """Validate files.json against FilesManifest schema."""
    return _validate_json_schema(
        file_path=manifest_path,
        schema_name="FilesManifest",
        file_id="manifest",
        evidence_output=evidence_output,
        validator=FilesManifest.model_validate_json,
    )


def validate_sections_schema(
    sections_path: Path,
    file_id: str,
    evidence_output: Path,
) -> dict[str, Any]:
    """Validate {file_id}.sections.json against FileSections schema."""
    return _validate_json_schema(
        file_path=sections_path,
        schema_name="FileSections",
        file_id=file_id,
        evidence_output=evidence_output,
        validator=FileSections.model_validate_json,
    )


def validate_atoms_schema(
    atoms_path: Path,
    file_id: str,
    evidence_output: Path,
) -> dict[str, Any]:
    """Validate {file_id}.atoms.jsonl against LineAtom schema."""
    issues: list[str] = []
    errors: list[str] = []

    try:
        with atoms_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    LineAtom.model_validate_json(stripped)
                except (ValidationError, ValueError) as exc:
                    errors.append(f"line {line_no}: {exc}")
    except OSError as exc:
        errors.append(f"Failed to read atoms file: {exc}")

    if errors:
        issues.extend(errors)
        _emit_schema_error(
            file_path=atoms_path,
            file_id=file_id,
            schema_name="LineAtom",
            errors=errors,
            evidence_output=evidence_output,
        )
        return {"valid": False, "issues": issues, "evidence_count": 1}

    return {"valid": True, "issues": issues, "evidence_count": 0}


def validate_terms_schema(
    terms_path: Path,
    file_id: str,
    evidence_output: Path,
) -> dict[str, Any]:
    """Validate {file_id}.terms.json against FileTerms schema."""
    return _validate_json_schema(
        file_path=terms_path,
        schema_name="FileTerms",
        file_id=file_id,
        evidence_output=evidence_output,
        validator=FileTerms.model_validate_json,
    )


def _validate_json_schema(
    *,
    file_path: Path,
    schema_name: str,
    file_id: str,
    evidence_output: Path,
    validator: Callable[[str], object],
) -> dict[str, Any]:
    issues: list[str] = []

    try:
        payload = file_path.read_text(encoding="utf-8")
        validator(payload)
    except (OSError, ValidationError, ValueError, json.JSONDecodeError) as exc:
        issues.append(str(exc))
        _emit_schema_error(
            file_path=file_path,
            file_id=file_id,
            schema_name=schema_name,
            errors=issues,
            evidence_output=evidence_output,
        )
        return {"valid": False, "issues": issues, "evidence_count": 1}

    return {"valid": True, "issues": issues, "evidence_count": 0}


def _emit_schema_error(
    *,
    file_path: Path,
    file_id: str,
    schema_name: str,
    errors: list[str],
    evidence_output: Path,
) -> None:
    error_message = errors[0] if errors else "Unknown schema validation error"
    evidence = GapEvidence(
        invariant_family="format",
        description=f"Schema validation failed: {error_message}",
        details={
            "file_id": file_id,
            "schema": schema_name,
            "validation_errors": [str(error) for error in errors],
            "file_path": str(file_path),
        },
        confidence=1.0,
        location=str(file_path),
        detector="schema-validator",
    )
    _emit_evidence(evidence, evidence_output)


def _emit_evidence(evidence: GapEvidence, output_path: Path) -> None:
    """Append evidence record to JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence.to_dict(), sort_keys=True) + "\n")
