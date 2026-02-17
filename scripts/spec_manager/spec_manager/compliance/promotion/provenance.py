# TODO(single-layer): RESTRUCTURE — Provenance concept survives (traceability is a
#   core tradeoff, TRADEOFFS.md). But "pin-function provenance" becomes "work item
#   provenance" — tracking which shape, which evidence, which phase produced a change.
#   Remove pin-function specific fields; adapt to shape-based audit trails.
# ALGORITHM(single-layer):
#   References: response3 Sections 8 and 11; tradeoff note on traceability.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] — three-phase forward-only pipeline.
#     - WorkItemProvenance: {work_item_id: str, shape_id: ShapeId, phase: PhaseId, introduced_by: str, modified_by: list[str], evidence_refs: list[str], source_locations: list[str], content_hash: str, created_at: str, updated_at: str}.
#     - ProvenanceRegistry: {records: dict[str, WorkItemProvenance], schema_version: str} keyed by work_item_id.
#   Interface contracts:
#     - def update_provenance_from_work_items(items: list[WorkItem], existing: ProvenanceRegistry, modifier: str) -> ProvenanceRegistry
#     - def check_provenance_complete(registry: ProvenanceRegistry, required_work_items: list[str], gate_spec: GateSpec) -> GateCheckResult
#   Control flow:
#     1. Replace pin_func_id-based updates with work_item_id-based updates.
#     2. On new work item, create record with phase/shape/evidence snapshot.
#     3. phase field must be one of 'libraries', 'architecture', 'quality' (forward-only, no cycling).
#     4. Each phase edits code via its own PromotionLoop with IMPLEMENT step — all phases do work.
#     5. On item mutation, append modifier and refresh hash/timestamps.
#     6. Gate check passes only when all required work items have provenance and non-empty shape_id+phase+evidence_refs.
#     7. Phase-local remediation if within authority; block if outside authority (no backtracking).
#   Error handling:
#     - Invalid/missing shape_id or phase is recorded as provenance finding and gate failure.
#     - Corrupt provenance file: recover empty registry and emit stale evidence failure.
#   Extraction boundary (§§13.1-13.3):
#     - Provenance evidence used for hard gate decisions must be deterministic (test results,
#       file hashes, controlled manifests). LLM-origin evidence (reviewer findings, call graph
#       inference) is recorded as advisory metadata only — it cannot cause gate pass/fail.
#     - If LLM evidence must matter, it must first be converted into a deterministic verifier
#       task (test/check) or an explicit human decision.
#   Integration points:
#     - Called by demotion/work_item pipeline and gate orchestrator.
#     - phase tracks which of the three phases (Libraries/Architecture/Quality) produced a change.
#   Test requirements:
#     - New/update provenance lifecycle.
#     - Completeness gate failure on missing fields.
#     - Migration from old pin data ignored without compatibility shim.
# IMPL(single-layer): Migrate this module to work-item provenance keyed by
# `work_item_id` with required `shape_id` + `phase`; keep deterministic evidence refs
# as hard-gate inputs and treat LLM-only metadata as advisory.

"""Provenance tracking for work items."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec_manager.compliance.promotion.config import GateId, GateSpec, PhaseId
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.routing.matcher import WorkItem

_VALID_PHASES = {"libraries", "architecture", "quality"}
_CORRUPT_SCHEMA_VERSION = "corrupt"
_LLM_EVIDENCE_HINTS = (
    "llm",
    "reasoning",
    "analysis",
    "human",
    "agent",
    "chat",
)
_DETERMINISTIC_EVIDENCE_PREFIXES = (
    "test",
    "tests",
    "matcher",
    "verifier",
    "contract",
    "manifest",
    "evidence",
    "artifact",
    "shape",
    "import",
    "diff",
    "phase",
    "proposal",
    "route",
    "file",
)
_DETERMINISTIC_EVIDENCE_EXTENSIONS = (
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".xml",
    ".csv",
)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_phase(raw_phase: Any) -> PhaseId | "":
    phase = _normalize_text(raw_phase).lower()
    if phase in _VALID_PHASES:
        return phase  # type: ignore[return-value]
    return ""


def _normalize_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for value in values:
        normalized.append(_normalize_text(value))
    return [value for value in normalized if value]


def _merge_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _default_source_location(
    file_path: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str:
    normalized_path = _normalize_text(file_path)
    if not normalized_path:
        return ""
    if line_start and line_start > 0:
        if line_end and line_end > 0 and line_end >= line_start:
            return f"{normalized_path}:{line_start}-{line_end}"
        return f"{normalized_path}:{line_start}"
    return normalized_path


def _source_location_from_object(location: Any) -> str:
    if location is None:
        return ""
    if isinstance(location, str):
        return _normalize_text(location)
    file_path = _normalize_text(
        getattr(location, "file", "") or getattr(location, "file_path", "")
    )
    if not file_path:
        return ""
    line_start = getattr(location, "line_start", None)
    line_hint = getattr(location, "line_hint", None)
    line_end = getattr(location, "line_end", None)
    if line_start is None:
        line_start = line_hint
    try:
        line_start_i = int(line_start) if line_start is not None else 0
    except (TypeError, ValueError):
        line_start_i = 0
    try:
        line_end_i = int(line_end) if line_end is not None else None
    except (TypeError, ValueError):
        line_end_i = None
    return _default_source_location(file_path, line_start_i, line_end_i)


def _extract_shape_id(item: WorkItem) -> str:
    return _normalize_text(getattr(item, "shape_id", ""))


def _extract_phase(item: WorkItem) -> PhaseId | "":
    return _normalize_phase(
        getattr(item, "created_in_phase", getattr(item, "phase", ""))
    )


def _extract_evidence_refs(item: WorkItem) -> list[str]:
    return _merge_unique(_normalize_list(getattr(item, "evidence_refs", [])))


def _extract_source_locations(item: WorkItem) -> list[str]:
    locations: list[str] = []
    location = getattr(item, "location", None)
    if location is not None:
        source_location = _source_location_from_object(location)
        if source_location:
            locations.append(source_location)

    file_locations = getattr(item, "file_locations", None)
    if file_locations is None:
        file_locations = getattr(item, "locations", None)
    if isinstance(file_locations, list):
        for raw_location in file_locations:
            source_location = _source_location_from_object(raw_location)
            if source_location:
                locations.append(source_location)

    if not locations:
        legacy_file = _normalize_text(getattr(item, "file", "") or getattr(item, "file_path", ""))
        if legacy_file:
            locations.append(legacy_file)

    return _merge_unique(locations)


def _is_deterministic_evidence_ref(ref: str) -> bool:
    normalized = _normalize_text(ref)
    if not normalized:
        return False
    lower = normalized.lower()
    if any(lower.startswith(f"{value}:") for value in _LLM_EVIDENCE_HINTS):
        return False
    if any(lower.startswith(f"{prefix}:") for prefix in _DETERMINISTIC_EVIDENCE_PREFIXES):
        return True
    if normalized.startswith(("file:", "http://", "https://", "//")):
        return True
    if any(token in normalized for token in ("/", "\\")):
        return True
    if any(lower.endswith(suffix) for suffix in _DETERMINISTIC_EVIDENCE_EXTENSIONS):
        return True
    return False


def _extract_deterministic_evidence_refs(evidence_refs: list[str]) -> list[str]:
    return _merge_unique([ref for ref in evidence_refs if _is_deterministic_evidence_ref(ref)])


def _has_deterministic_phase(phase: str) -> bool:
    return bool(_normalize_phase(phase))


def _work_item_fingerprint(
    item: WorkItem,
    shape_id: str,
    phase: str,
    evidence_refs: list[str],
    source_locations: list[str],
) -> str:
    payload = {
        "work_item_id": _normalize_text(getattr(item, "work_item_id", "")),
        "shape_id": shape_id,
        "phase": phase,
        "evidence_refs": sorted(_merge_unique(evidence_refs)),
        "source_locations": sorted(_merge_unique(source_locations)),
        "required_change_type": _normalize_text(
            getattr(item, "required_change_type", "")
        ),
        "status": _normalize_text(getattr(item, "status", "")),
        "kind": _normalize_text(getattr(item, "kind", "")),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    ).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass
# IMPL(single-layer): Replace `AtomProvenance` with `WorkItemProvenance`
# (Sections 8.1/11) and delete pin-function-only fields in the same change
# (`pin_func_id`, `function_name`, `file_path`).
class WorkItemProvenance:
    work_item_id: str
    shape_id: str
    phase: PhaseId | ""
    introduced_by: str
    modified_by: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    source_locations: list[str] = field(default_factory=list)
    content_hash: str = ""
    created_at: str = ""
    updated_at: str = ""

    def add_modification(self, modifier: str) -> None:
        if modifier and modifier not in self.modified_by:
            self.modified_by.append(modifier)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "shape_id": self.shape_id,
            "phase": self.phase,
            "introduced_by": self.introduced_by,
            "modified_by": self.modified_by,
            "evidence_refs": self.evidence_refs,
            "source_locations": self.source_locations,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkItemProvenance:
        phase = _normalize_phase(data.get("phase"))
        if not phase and _normalize_text(data.get("phase")):
            phase = _normalize_text(data.get("phase"))
        return cls(
            work_item_id=_normalize_text(data.get("work_item_id", "")),
            shape_id=_normalize_text(data.get("shape_id", "")),
            phase=phase,
            introduced_by=_normalize_text(data.get("introduced_by", "")),
            modified_by=_merge_unique(_normalize_list(data.get("modified_by", []))),
            evidence_refs=_merge_unique(_normalize_list(data.get("evidence_refs", []))),
            source_locations=_merge_unique(_normalize_list(data.get("source_locations", []))),
            content_hash=_normalize_text(data.get("content_hash", "")),
            created_at=_normalize_text(data.get("created_at", "")),
            updated_at=_normalize_text(data.get("updated_at", "")),
        )


@dataclass
# IMPL(single-layer): Registry records should be keyed by `work_item_id`; do not
# retain dual key paths or pin-era compatibility shims when this migration lands.
class ProvenanceRegistry:
    records: dict[str, WorkItemProvenance] = field(default_factory=dict)
    schema_version: str = "1.0"

    def get(self, work_item_id: str) -> WorkItemProvenance | None:
        return self.records.get(work_item_id)

    def upsert(self, provenance: WorkItemProvenance) -> None:
        self.records[provenance.work_item_id] = provenance

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "records": {k: v.to_dict() for k, v in self.records.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceRegistry:
        schema_version = _normalize_text(data.get("schema_version", "1.0"))
        if not schema_version:
            schema_version = "1.0"
        registry = cls(schema_version=schema_version)
        raw_records = data.get("records", {})
        if not isinstance(raw_records, dict):
            registry.schema_version = _CORRUPT_SCHEMA_VERSION
            return registry

        for key, record_data in raw_records.items():
            if not isinstance(key, str):
                continue
            if not isinstance(record_data, dict):
                continue
            registry.records[key] = WorkItemProvenance.from_dict(record_data)
        return registry

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ProvenanceRegistry:
        # IMPL(single-layer): Corrupt/invalid provenance payloads must surface as
        # stale deterministic evidence failures at gate orchestration boundaries.
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return cls(schema_version=_CORRUPT_SCHEMA_VERSION)
        if not isinstance(data, dict):
            return cls(schema_version=_CORRUPT_SCHEMA_VERSION)
        try:
            return cls.from_dict(data)
        except (TypeError, ValueError):
            return cls(schema_version=_CORRUPT_SCHEMA_VERSION)


# IMPL(single-layer): Replace this updater with
# `update_provenance_from_work_items(items, existing, modifier)` so phase routing
# captures shape ownership and verifier-backed evidence refs per work item.
def update_provenance_from_work_items(
    items: list[WorkItem],
    existing_provenance: ProvenanceRegistry,
    modifier: str,
) -> ProvenanceRegistry:
    now = _now_iso()
    records = {
        key: WorkItemProvenance.from_dict(record.to_dict())
        for key, record in existing_provenance.records.items()
    }
    updated = ProvenanceRegistry(
        schema_version=existing_provenance.schema_version,
        records=records,
    )
    normalized_modifier = _normalize_text(modifier) or "scan"

    for item in items:
        work_item_id = _normalize_text(getattr(item, "work_item_id", ""))
        if not work_item_id:
            continue

        shape_id = _extract_shape_id(item)
        phase = _extract_phase(item)
        evidence_refs = _extract_evidence_refs(item)
        source_locations = _extract_source_locations(item)
        content_hash = _work_item_fingerprint(
            item,
            shape_id=shape_id,
            phase=phase,
            evidence_refs=evidence_refs,
            source_locations=source_locations,
        )

        existing = updated.get(work_item_id)
        if existing is None:
            updated.upsert(
                WorkItemProvenance(
                    work_item_id=work_item_id,
                    shape_id=shape_id,
                    phase=phase,
                    introduced_by=normalized_modifier,
                    modified_by=[],
                    evidence_refs=evidence_refs,
                    source_locations=source_locations,
                    content_hash=content_hash,
                    created_at=now,
                    updated_at=now,
                )
            )
            continue

        if content_hash != existing.content_hash:
            existing.add_modification(normalized_modifier)
            existing.content_hash = content_hash
            existing.updated_at = now

        if shape_id:
            existing.shape_id = shape_id
        if phase:
            existing.phase = phase

        if evidence_refs:
            existing.evidence_refs = _merge_unique(existing.evidence_refs + evidence_refs)
        if source_locations:
            existing.source_locations = _merge_unique(
                existing.source_locations + source_locations
            )

        if not existing.updated_at and content_hash != existing.content_hash:
            existing.updated_at = now

    return updated


# IMPL(single-layer): Replace pin-registry completeness with
# `check_provenance_complete(registry, required_work_items, gate_spec)` driven by
# matcher/work-item queues; fail missing `shape_id`/`phase`/`evidence_refs`.
def check_provenance_complete(
    provenance_registry: ProvenanceRegistry,
    required_work_items: list[str],
    gate_spec: GateSpec,
) -> GateCheckResult:
    start = time.monotonic()
    required = _merge_unique(_normalize_list(required_work_items))
    findings: list[dict[str, Any]] = []

    for work_item_id in required:
        record = provenance_registry.get(work_item_id)
        issues: list[str] = []

        if record is None:
            issues.append("No provenance record found")
        else:
            if not _normalize_text(record.shape_id):
                issues.append("Missing shape_id")
            if not _has_deterministic_phase(record.phase):
                issues.append("Missing or invalid phase")
            if not _extract_deterministic_evidence_refs(record.evidence_refs):
                issues.append("Missing deterministic evidence_refs")

        if issues:
            findings.append(
                {
                    "work_item_id": work_item_id,
                    "shape_id": record.shape_id if record is not None else "",
                    "phase": record.phase if record is not None else "",
                    "evidence_refs": (
                        _extract_deterministic_evidence_refs(record.evidence_refs)
                        if record is not None
                        else []
                    ),
                    "issues": issues,
                }
            )

    if provenance_registry.schema_version == _CORRUPT_SCHEMA_VERSION:
        findings.append(
            {
                "work_item_id": "__provenance_registry__",
                "shape_id": "",
                "phase": "",
                "evidence_refs": ["provenance_registry:corrupt"],
                "issues": ["Stale provenance registry evidence"],
            }
        )

    total = len(required)
    complete = total - len([finding for finding in findings if finding["work_item_id"] != "__provenance_registry__"])

    if provenance_registry.schema_version == _CORRUPT_SCHEMA_VERSION and total == 0:
        complete = 0

    passed = len(findings) == 0
    duration = (time.monotonic() - start) * 1000
    score = (complete / total) if total > 0 else (1.0 if not findings else 0.0)

    if provenance_registry.schema_version == _CORRUPT_SCHEMA_VERSION:
        summary = "Stale provenance registry evidence"
    elif passed:
        summary = f"All {total} work item(s) have complete provenance"
    else:
        summary = f"{len(findings)} of {total} required work item(s) missing complete provenance"

    return GateCheckResult(
        gate_id=GateId.PROVENANCE_COMPLETE.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=score,
        findings=findings,
        summary=summary,
        duration_ms=duration,
    )
