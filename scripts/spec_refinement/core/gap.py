"""Gap data structures and synthesis for spec refinement."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, cast

from spec_manager.core.gaps import Severity


class GapType(Enum):
    """Supported gap types for spec refinement."""

    missing_detail = "missing_detail"
    contradiction = "contradiction"
    ambiguity = "ambiguity"
    out_of_scope = "out_of_scope"
    needs_decision = "needs_decision"
    coverage_failure = "coverage_failure"
    membership_failure = "membership_failure"
    entity_resolution_failure = "entity_resolution_failure"
    proof_chain_break = "proof_chain_break"
    sequence_violation = "sequence_violation"
    content_mismatch = "content_mismatch"
    uncertainty_marker = "uncertainty_marker"
    format_violation = "format_violation"


@dataclass
class GapEvidence:
    """Evidence supporting a gap identification."""

    invariant_family: str
    description: str
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    location: str | None = None
    detector: str | None = None

    @staticmethod
    def _serialize_details(details: dict[str, Any]) -> dict[str, Any]:
        """Convert details dict to JSON-serializable form."""

        def make_serializable(obj: object) -> object:
            if obj is None or isinstance(obj, (bool, int, float, str)):
                return obj
            if isinstance(obj, (list, tuple)):
                return [make_serializable(item) for item in obj]
            if isinstance(obj, dict):
                return {str(k): make_serializable(v) for k, v in obj.items()}
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise ValueError(
                f"Unsupported type in details: {type(obj).__name__}. "
                "Details must contain only JSON-serializable types, Path, or datetime."
            )

        return {str(k): make_serializable(v) for k, v in details.items()}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "invariant_family": self.invariant_family,
            "description": self.description,
            "details": self._serialize_details(self.details),
            "confidence": self.confidence,
            "location": self.location,
            "detector": self.detector,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GapEvidence:
        """Deserialize from dictionary."""
        return cls(
            invariant_family=data["invariant_family"],
            description=data["description"],
            details=data.get("details", {}),
            confidence=data.get("confidence", 1.0),
            location=data.get("location"),
            detector=data.get("detector"),
        )


@dataclass
class Gap:
    """First-class gap element with evidence-based identification."""

    id: str
    gap_type: GapType
    severity: Severity
    source: list[str]
    derived_artifact_target: str
    description: str
    evidence: list[GapEvidence] = field(default_factory=list)
    status: Literal["open", "integrated", "deferred", "rejected"] = "open"
    resolution_pointer: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: str | None = None
    resolution_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "gap_type": self.gap_type.value,
            "severity": self.severity.value,
            "source": list(self.source),
            "derived_artifact_target": self.derived_artifact_target,
            "description": self.description,
            "evidence": [e.to_dict() for e in self.evidence],
            "status": self.status,
            "resolution_pointer": self.resolution_pointer,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolution_notes": self.resolution_notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Gap:
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            gap_type=GapType(data["gap_type"]),
            severity=Severity(data["severity"]),
            source=data.get("source", []),
            derived_artifact_target=data.get("derived_artifact_target", ""),
            description=data.get("description", ""),
            evidence=[GapEvidence.from_dict(e) for e in data.get("evidence", [])],
            status=data.get("status", "open"),
            resolution_pointer=data.get("resolution_pointer"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            resolved_at=data.get("resolved_at"),
            resolution_notes=data.get("resolution_notes"),
        )


def _safe_serialize_details(details: dict[str, Any]) -> str:
    """Serialize details for stable hashing."""

    def make_serializable(obj: object) -> object:
        if obj is None or isinstance(obj, (bool, int, float, str)):
            return obj
        if isinstance(obj, (list, tuple)):
            return [make_serializable(item) for item in obj]
        if isinstance(obj, dict):
            return {str(k): make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise ValueError(
            f"Unsupported type in evidence details: {type(obj).__name__}. "
            "Details must contain only JSON-serializable types, Path, or datetime."
        )

    serializable_details = make_serializable(details)
    return json.dumps(serializable_details, sort_keys=True)


def compute_evidence_signature(evidence_list: list[GapEvidence]) -> str:
    """Compute a stable signature from a list of gap evidence."""
    if not evidence_list:
        raise ValueError(
            "Cannot compute signature for empty evidence list. "
            "Gaps must have at least one piece of supporting evidence."
        )

    def _make_sort_key(evidence: GapEvidence) -> tuple[str, str, str, str, str, float]:
        location = evidence.location or ""
        detector = evidence.detector or ""
        confidence = round(evidence.confidence, 2)
        details_canonical = _safe_serialize_details(evidence.details)
        return (
            evidence.invariant_family,
            evidence.description,
            details_canonical,
            location,
            detector,
            confidence,
        )

    sorted_evidence = sorted(evidence_list, key=_make_sort_key)
    canonical_parts = []
    for evidence in sorted_evidence:
        location = evidence.location or ""
        detector = evidence.detector or ""
        confidence = round(evidence.confidence, 2)
        details_str = _safe_serialize_details(evidence.details)
        canonical_parts.append(
            f"{evidence.invariant_family}:{evidence.description}:"
            f"{details_str}:{location}:{detector}:{confidence}"
        )

    canonical_str = "|".join(canonical_parts)
    hash_digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
    return hash_digest[:8]


def _cluster_by_target(evidence: list[GapEvidence]) -> dict[str, list[GapEvidence]]:
    """Group evidence by derived artifact target."""
    clusters: dict[str, list[GapEvidence]] = {}
    for item in evidence:
        target = _extract_target(item)
        clusters.setdefault(target, []).append(item)
    return clusters


def _cluster_by_invariant(evidence: list[GapEvidence]) -> dict[str, list[GapEvidence]]:
    """Group evidence by invariant family."""
    clusters: dict[str, list[GapEvidence]] = {}
    for item in evidence:
        clusters.setdefault(item.invariant_family, []).append(item)
    return clusters


def _synthesize_description(evidence: list[GapEvidence]) -> str:
    """Create a human-readable summary from evidence."""
    unique = []
    for item in evidence:
        if item.description not in unique:
            unique.append(item.description)
    if not unique:
        return "Gap detected"
    if len(unique) == 1:
        return unique[0]
    summary = "; ".join(unique[:3])
    if len(unique) > 3:
        summary = f"{summary}; ..."
    return summary


def _extract_target(evidence: GapEvidence) -> str:
    target = evidence.details.get("derived_artifact_target")
    if isinstance(target, str) and target:
        return target
    return "unknown"


def _extract_sources(evidence: GapEvidence) -> list[str]:
    sources = evidence.details.get("source")
    if sources is None:
        sources = evidence.details.get("sources")
    if sources is None:
        return []
    if isinstance(sources, str):
        return [sources]
    if isinstance(sources, list):
        return [str(item) for item in sources if item is not None]
    return [str(sources)]


def _extract_severity(evidence: GapEvidence) -> Severity | None:
    raw = evidence.details.get("severity")
    if isinstance(raw, Severity):
        return raw
    if isinstance(raw, str):
        try:
            return Severity(raw)
        except ValueError:
            return None
    return None


def _infer_gap_type(evidence: list[GapEvidence]) -> GapType:
    for item in evidence:
        raw = item.details.get("gap_type")
        if isinstance(raw, GapType):
            return raw
        if isinstance(raw, str):
            try:
                return GapType(raw)
            except ValueError:
                continue

    invariant = evidence[0].invariant_family if evidence else ""
    mapping = {
        "coverage": GapType.coverage_failure,
        "membership": GapType.membership_failure,
        "entity_resolution": GapType.entity_resolution_failure,
        "proof": GapType.proof_chain_break,
        "sequence": GapType.sequence_violation,
        "content": GapType.content_mismatch,
        "uncertainty": GapType.uncertainty_marker,
        "format": GapType.format_violation,
        "contradiction": GapType.contradiction,
        "ambiguity": GapType.ambiguity,
        "out_of_scope": GapType.out_of_scope,
        "needs_decision": GapType.needs_decision,
    }
    return mapping.get(invariant, GapType.missing_detail)


class GapSynthesizer:
    """Synthesizes gaps from clustered evidence."""

    def cluster_evidence(self, findings: list[GapEvidence]) -> list[Gap]:
        """Cluster evidence into synthesized gaps."""
        gaps: list[Gap] = []
        target_clusters = _cluster_by_target(findings)
        for target, target_evidence in target_clusters.items():
            invariant_clusters = _cluster_by_invariant(target_evidence)
            for invariant_evidence in invariant_clusters.values():
                clusters: list[dict[str, Any]] = []
                for item in invariant_evidence:
                    sources = set(_extract_sources(item))
                    if not sources:
                        clusters.append({"evidence": [item], "sources": set()})
                        continue
                    matched_indexes = [
                        index
                        for index, cluster in enumerate(clusters)
                        if sources & cluster["sources"]
                    ]
                    if not matched_indexes:
                        clusters.append({"evidence": [item], "sources": set(sources)})
                        continue
                    primary_index = matched_indexes[0]
                    clusters[primary_index]["evidence"].append(item)
                    clusters[primary_index]["sources"].update(sources)
                    for index in reversed(matched_indexes[1:]):
                        clusters[primary_index]["evidence"].extend(clusters[index]["evidence"])
                        clusters[primary_index]["sources"].update(clusters[index]["sources"])
                        clusters.pop(index)

                for cluster in clusters:
                    evidence_list = cluster["evidence"]
                    signature = compute_evidence_signature(evidence_list)
                    gap_id = f"GAP-{signature}"
                    severity = Severity.INFO
                    for item in evidence_list:
                        candidate = _extract_severity(item)
                        if candidate is None:
                            continue
                        if candidate == Severity.ERROR:
                            severity = Severity.ERROR
                            break
                        if candidate == Severity.WARNING and severity == Severity.INFO:
                            severity = Severity.WARNING
                    description = _synthesize_description(evidence_list)
                    gap_sources = sorted(
                        {src for item in evidence_list for src in _extract_sources(item)}
                    )
                    gap_type = _infer_gap_type(evidence_list)
                    gaps.append(
                        Gap(
                            id=gap_id,
                            gap_type=gap_type,
                            severity=severity,
                            source=gap_sources,
                            derived_artifact_target=target,
                            description=description,
                            evidence=evidence_list,
                        )
                    )

        return gaps

    def merge_gaps(self, existing: list[Gap], new: list[Gap]) -> list[Gap]:
        """Merge new gaps into existing set based on evidence signatures."""
        merged: dict[str, Gap] = {}
        for gap in existing:
            signature = compute_evidence_signature(gap.evidence)
            merged[signature] = gap

        for gap in new:
            signature = compute_evidence_signature(gap.evidence)
            if signature in merged:
                current = merged[signature]
                existing_evidence = {
                    json.dumps(e.to_dict(), sort_keys=True): e for e in current.evidence
                }
                for evidence in gap.evidence:
                    key = json.dumps(evidence.to_dict(), sort_keys=True)
                    if key not in existing_evidence:
                        current.evidence.append(evidence)
                current.source = sorted(set(current.source) | set(gap.source))
                if current.derived_artifact_target == "unknown":
                    current.derived_artifact_target = gap.derived_artifact_target
                current.severity = _max_severity(current.severity, gap.severity)
                current.gap_type = gap.gap_type
                current.description = _synthesize_description(current.evidence)
                continue
            merged[signature] = gap

        return list(merged.values())


def _max_severity(left: Severity, right: Severity) -> Severity:
    order = {Severity.ERROR: 3, Severity.WARNING: 2, Severity.INFO: 1}
    return left if order[left] >= order[right] else right


def format_gap_table(gaps: list[Gap], max_desc_len: int = 60) -> str:
    """Format gaps as an ASCII table."""
    headers = ["ID", "Type", "Severity", "Status", "Artifact", "Description"]
    rows: list[list[str]] = []
    for gap in gaps:
        description = gap.description
        if len(description) > max_desc_len:
            description = f"{description[: max_desc_len - 3]}..."
        rows.append(
            [
                gap.id,
                gap.gap_type.value,
                gap.severity.value,
                gap.status,
                gap.derived_artifact_target,
                description,
            ]
        )

    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def _format_row(items: list[str]) -> str:
        return " | ".join(item.ljust(widths[index]) for index, item in enumerate(items))

    separator = "-+-".join("-" * width for width in widths)
    table_lines = [_format_row(headers), separator]
    table_lines.extend(_format_row(row) for row in rows)
    return "\n".join(table_lines)


def format_gap_markdown(gap: Gap) -> str:
    """Format a single gap as markdown section."""
    resolved_at = gap.resolved_at or "N/A"
    resolution_pointer = gap.resolution_pointer or "N/A"
    resolution_notes = gap.resolution_notes or "N/A"

    lines = [
        f"### {gap.id}: {gap.description}",
        f"- **Type**: {gap.gap_type.value}",
        f"- **Severity**: {gap.severity.value}",
        f"- **Status**: {gap.status}",
        f"- **Artifact**: {gap.derived_artifact_target}",
        f"- **Created**: {gap.created_at}",
        f"- **Resolved**: {resolved_at}",
        f"- **Resolution Pointer**: {resolution_pointer}",
        f"- **Resolution Notes**: {resolution_notes}",
        "- **Source**:",
    ]

    if gap.source:
        lines.extend(f"  - {source}" for source in gap.source)
    else:
        lines.append("  - N/A")

    lines.append("- **Evidence**:")
    if gap.evidence:
        for evidence in gap.evidence:
            details = json.dumps(GapEvidence._serialize_details(evidence.details), sort_keys=True)
            detector = evidence.detector or ""
            location = evidence.location or ""
            lines.append(
                "  - "
                f"confidence={evidence.confidence} | "
                f"invariant_family={evidence.invariant_family} | "
                f"detector={detector} | "
                f"location={location} | "
                f"description={evidence.description} | "
                f"details={details}"
            )
    else:
        lines.append("  - N/A")

    return "\n".join(lines)


def parse_gaps_markdown(content: str) -> list[Gap]:
    """Parse gaps.md markdown content into Gap objects."""
    gaps: list[Gap] = []
    current_section_status: Literal["open", "integrated", "deferred", "rejected"] | None = None
    current_gap_id: str | None = None
    current_gap_description: str | None = None
    current_gap_lines: list[str] = []

    def _flush_gap() -> None:
        nonlocal current_gap_id, current_gap_description, current_gap_lines, current_section_status
        if not current_gap_id:
            return
        gap = _parse_gap_block(
            current_gap_id,
            current_gap_description or "",
            current_gap_lines,
            current_section_status or "open",
        )
        gaps.append(gap)
        current_gap_id = None
        current_gap_description = None
        current_gap_lines = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            _flush_gap()
            section_name = stripped[3:].strip().lower()
            if section_name.startswith("open"):
                current_section_status = "open"
            elif section_name.startswith("integrated"):
                current_section_status = "integrated"
            elif section_name.startswith("deferred"):
                current_section_status = "deferred"
            elif section_name.startswith("rejected"):
                current_section_status = "rejected"
            else:
                current_section_status = None
            continue
        if stripped.startswith("### "):
            _flush_gap()
            header = stripped[4:].strip()
            if ":" in header:
                gap_id, description = header.split(":", 1)
                current_gap_id = gap_id.strip()
                current_gap_description = description.strip()
            else:
                current_gap_id = header
                current_gap_description = ""
            current_gap_lines = []
            continue
        if current_gap_id:
            current_gap_lines.append(line)

    _flush_gap()
    return gaps


_VALID_STATUSES: set[str] = {"open", "integrated", "deferred", "rejected"}


def _parse_gap_block(
    gap_id: str,
    description: str,
    lines: list[str],
    section_status: Literal["open", "integrated", "deferred", "rejected"],
) -> Gap:
    gap_type = GapType.missing_detail
    severity = Severity.WARNING
    status: Literal["open", "integrated", "deferred", "rejected"] = section_status
    derived_artifact_target = ""
    source: list[str] = []
    evidence: list[GapEvidence] = []
    created_at = datetime.now().isoformat()
    resolved_at: str | None = None
    resolution_pointer: str | None = None
    resolution_notes: str | None = None
    mode: str | None = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- **"):
            mode = None
            label, _, value = stripped.partition(":")
            label = label.replace("- **", "").replace("**", "").strip()
            value = value.strip()
            if label == "Type" and value:
                try:
                    gap_type = GapType(value)
                except ValueError:
                    gap_type = GapType.missing_detail
            elif label == "Severity" and value:
                try:
                    severity = Severity(value)
                except ValueError:
                    severity = Severity.WARNING
            elif label == "Status" and value and value in _VALID_STATUSES:
                status = cast("Literal['open', 'integrated', 'deferred', 'rejected']", value)
            elif label == "Artifact" and value:
                derived_artifact_target = value
            elif label == "Created" and value:
                created_at = value
            elif label == "Resolved":
                resolved_at = None if value in {"", "N/A", "None"} else value
            elif label == "Resolution Pointer":
                resolution_pointer = None if value in {"", "N/A", "None"} else value
            elif label == "Resolution Notes":
                resolution_notes = None if value in {"", "N/A", "None"} else value
            elif label == "Source":
                mode = "source"
            elif label == "Evidence":
                mode = "evidence"
            continue

        if stripped.startswith("- ") and mode == "source":
            entry = stripped[2:].strip()
            if entry and entry not in {"N/A", "None"}:
                source.append(entry)
            continue

        if stripped.startswith("- ") and mode == "evidence":
            entry = stripped[2:].strip()
            if entry in {"N/A", "None"}:
                continue
            evidence.append(_parse_evidence_entry(entry))
            continue

        if stripped.startswith("- **"):
            mode = None

    return Gap(
        id=gap_id,
        gap_type=gap_type,
        severity=severity,
        source=source,
        derived_artifact_target=derived_artifact_target,
        description=description,
        evidence=evidence,
        status=status,
        resolution_pointer=resolution_pointer,
        created_at=created_at,
        resolved_at=resolved_at,
        resolution_notes=resolution_notes,
    )


def _parse_evidence_entry(entry: str) -> GapEvidence:
    data: dict[str, str] = {}
    parts = [part.strip() for part in entry.split("|")]
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            data[key.strip()] = value.strip()

    confidence = float(data.get("confidence", 1.0))
    invariant_family = data.get("invariant_family", "")
    description = data.get("description", "")
    detector = data.get("detector") or None
    location = data.get("location") or None
    details_raw = data.get("details", "{}")
    try:
        details = json.loads(details_raw)
    except json.JSONDecodeError:
        details = {}

    return GapEvidence(
        invariant_family=invariant_family,
        description=description,
        details=details,
        confidence=confidence,
        location=location,
        detector=detector,
    )
