"""Schemas and helpers for library structure review actions."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from spec_manager.refinement.formats import parse_evidence_pointer
from spec_manager.refinement.validation_utils import build_file_id_lookup

ACTION_ID_RE = re.compile(r"^ACT-\d{4}$")
LIB_ID_RE = re.compile(r"^LIB-\d{4}$")
ELEMENT_ID_RE = re.compile(
    r"^(?:REQ-LIB-\d{4}-\d{4}|FLOW-LIB-\d{4}-\d{2}|INV-LIB-\d{4}-\d{4}|DEC-LIB-\d{4}-\d{4})$"
)
MULTI_HOP_POINTER_RE = re.compile(r"^\[LIB-\d{4}::[^:]+::[^\]]+\]$")
SOURCE_POINTER_RE = re.compile(r"^\[spec_snapshot/[^:]+::SEC-[A-Za-z0-9]+-\d{4}\]$")
KNOWN_LIBRARY_SPEC_FILES = frozenset(
    {
        "spec.md",
        "spec",
        "charter.md",
        "charter",
        "decisions.md",
        "decisions",
    }
)
MULTI_HOP_SECTION_RE = re.compile(
    r"^(?:"
    r"REQ-LIB-\d{4}-\d{4}"
    r"|FLOW-LIB-\d{4}-\d{2}"
    r"|INV-LIB-\d{4}-\d{4}"
    r"|DEC-LIB-\d{4}-\d{4}"
    r"|SEC-[A-Za-z0-9]+-\d{4}"
    r"|[A-Za-z][A-Za-z0-9_ ]*"
    r")$"
)


def _validate_iso8601(value: str) -> str:
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("value must be ISO-8601") from exc
    return value


def validate_pointer_format(pointer: str) -> bool:
    return bool(
        MULTI_HOP_POINTER_RE.fullmatch(pointer) or SOURCE_POINTER_RE.fullmatch(pointer)
    )


class ReviewAction(BaseModel):
    action_id: str
    type: Literal["split", "merge", "move_elements", "deprecate"]
    status: Literal["proposed", "applied", "rejected"]
    source_libs: list[str]
    target_libs: list[str]
    elements: list[str]
    summary: str
    rationale: str
    evidence: list[str]
    notes: str | None = None

    @field_validator("action_id")
    @classmethod
    def validate_action_id(cls, value: str) -> str:
        if not ACTION_ID_RE.fullmatch(value):
            raise ValueError("action_id must match ACT-####")
        return value

    @field_validator("source_libs", "target_libs")
    @classmethod
    def validate_lib_ids(cls, value: list[str]) -> list[str]:
        for lib_id in value:
            if not LIB_ID_RE.fullmatch(lib_id):
                raise ValueError("library IDs must match LIB-####")
        return value

    @field_validator("elements")
    @classmethod
    def validate_elements(cls, value: list[str]) -> list[str]:
        for element_id in value:
            if not ELEMENT_ID_RE.fullmatch(element_id):
                raise ValueError(
                    "element IDs must match REQ-LIB-####-####, FLOW-LIB-####-##, "
                    "INV-LIB-####-####, or DEC-LIB-####-####"
                )
        return value

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: list[str]) -> list[str]:
        for pointer in value:
            if not validate_pointer_format(pointer):
                raise ValueError(
                    "evidence pointers must be multi-hop library or spec_snapshot pointers"
                )
        return value


class ReviewActionsReport(BaseModel):
    run_id: str
    generated_at: str
    thresholds: dict[str, float] = Field(
        default_factory=lambda: {"overlap_similarity": 0.35, "min_shared_elements": 5}
    )
    actions: list[ReviewAction]

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        return _validate_iso8601(value)


def allocate_action_id(
    *,
    existing_actions: list[ReviewAction] | None = None,
    existing_ids: set[str] | None = None,
) -> str:
    if existing_actions is not None and existing_ids is not None:
        raise ValueError("Provide either existing_actions or existing_ids, not both.")
    if existing_actions is None and existing_ids is None:
        existing_ids = set()

    ids: set[str]
    if existing_actions is not None:
        ids = {action.action_id for action in existing_actions}
    else:
        ids = set(existing_ids or set())

    numbers: list[int] = []
    for action_id in ids:
        if ACTION_ID_RE.fullmatch(action_id):
            numbers.append(int(action_id.split("-", 1)[1]))

    next_number = max(numbers, default=0) + 1
    if next_number > 9999:
        raise ValueError("Unable to allocate new action ID beyond ACT-9999.")
    return f"ACT-{next_number:04d}"


def generate_stable_action_ids(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _sort_key(action: dict[str, Any]) -> tuple[Any, list[str], list[str], list[str]]:
        return (
            action["type"],
            sorted(action["source_libs"]),
            sorted(action.get("target_libs", [])),
            sorted(action.get("elements", [])),
        )

    sorted_actions = sorted(actions, key=_sort_key)
    assigned: list[dict[str, Any]] = []
    for index, action in enumerate(sorted_actions, start=1):
        payload = dict(action)
        payload["action_id"] = f"ACT-{index:04d}"
        assigned.append(payload)
    return assigned


def validate_pointer_references(
    pointer: str,
    file_manifest: dict[str, dict[str, str]],
    allocated_library_ids: set[str],
) -> tuple[bool, str | None]:
    parsed = parse_evidence_pointer(pointer, allow_multi_hop=True)
    if not parsed:
        return False, "Invalid evidence pointer format."
    if "intermediate" in parsed:
        lib_id = parsed["file_ref"]
        if lib_id not in allocated_library_ids:
            return False, f"Unknown library id '{lib_id}'."
        intermediate = parsed["intermediate"]
        if intermediate not in KNOWN_LIBRARY_SPEC_FILES:
            return False, f"Unknown spec file '{intermediate}' for library '{lib_id}'."
        section_ref = parsed["section_ref"]
        if not MULTI_HOP_SECTION_RE.fullmatch(section_ref):
            return False, f"Invalid section reference '{section_ref}' in multi-hop pointer."
        return True, None
    if parsed.get("format") == "new":
        file_lookup = build_file_id_lookup(file_manifest)
        file_ref = parsed["file_ref"]
        if file_ref not in file_lookup and f"spec_snapshot/{file_ref}" not in file_lookup:
            return False, f"Unknown file reference '{file_ref}'."
        return True, None
    return False, "Unsupported evidence pointer format."


def write_review_actions_json(report: ReviewActionsReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump()
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_review_actions_json(input_path: Path) -> ReviewActionsReport:
    content = input_path.read_text(encoding="utf-8")
    return ReviewActionsReport.model_validate(json.loads(content))


def write_review_actions_markdown(report: ReviewActionsReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def _join(items: list[str]) -> str:
        return ", ".join(items) if items else "-"

    def _escape_table(value: str) -> str:
        return value.replace("|", "\\|")

    thresholds = ", ".join(
        f"{key}={value}" for key, value in sorted(report.thresholds.items())
    )

    lines: list[str] = [
        "# Library Structure Review Actions",
        "",
        "## Metadata",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Run ID | {report.run_id} |",
        f"| Generated At | {report.generated_at} |",
        f"| Thresholds | {thresholds or '-'} |",
        "",
        "## Actions Summary",
        "",
        "| Action ID | Type | Status | Source Libraries | Target Libraries | Summary |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for action in report.actions:
        lines.append(
            "| "
            + " | ".join(
                [
                    action.action_id,
                    action.type,
                    action.status,
                    _join(action.source_libs),
                    _join(action.target_libs),
                    _escape_table(action.summary),
                ]
            )
            + " |"
        )

    lines.append("")
    lines.append("## Action Details")

    for action in report.actions:
        lines.extend(
            [
                "",
                f"### {action.action_id}: {action.type}",
                "",
                "#### Rationale",
                "",
                action.rationale or "-",
                "",
                "#### Evidence",
                "",
            ]
        )
        if action.evidence:
            lines.extend([f"- {pointer}" for pointer in action.evidence])
        else:
            lines.append("- None")
        lines.extend(["", "#### Notes", "", action.notes or "-"])

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
