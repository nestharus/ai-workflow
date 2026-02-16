"""Compliance scoring and gate evaluation for spec processing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from spec_manager.core.data_structures import ComplianceMetrics
from spec_manager.core.gaps import Severity

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from spec_manager.compliance.promotion.config import PromotionGateConfig
    from spec_manager.schemas.pin_functions import PinFunctionRegistry


class Evidence(Protocol):
    """Protocol for compliance evidence with standardized fields."""

    detector: str
    severity: str | Severity
    details: dict[str, Any] | None
    message: str


@dataclass
class _EvidenceRecord:
    detector: str
    severity: str
    message: str
    details: dict[str, Any]


@dataclass
class ComplianceResult:
    """Result of compliance scoring."""

    score: float  # 0.0-1.0
    blockers: list[dict[str, Any]]  # Blocking issues
    warnings: list[dict[str, Any]]  # Warning issues
    passed: bool  # True if no blockers
    details: dict[str, Any]  # Detailed metrics
    pass_num: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to compliance.json schema."""
        return {
            "pass": self.pass_num or 0,
            "score": self.score,
            "passed": self.passed,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "details": self.details,
        }

    def save(self, path: Path) -> None:
        """Write compliance.json to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


class ComplianceScorer:
    """Scores compliance and categorizes blockers/warnings."""

    def __init__(self, blocker_threshold: float = 0.0, warning_threshold: float = 0.05) -> None:
        """Initialize compliance scorer with thresholds."""
        self.blocker_threshold = blocker_threshold
        self.warning_threshold = warning_threshold

    def score_run_compliance(
        self,
        run_root: Path,
        pass_num: int = 2,
    ) -> ComplianceResult:
        """Score compliance using run-root manifest artifacts."""
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        blockers.extend(self.check_artifact_presence(run_root))
        blockers.extend(self.check_schema_validity(run_root))
        blockers.extend(self.check_section_spans(run_root))

        evidence, evidence_blockers, evidence_warnings = self._load_run_evidence(run_root)
        blockers.extend(evidence_blockers)
        warnings.extend(evidence_warnings)

        if not evidence:
            blockers.append(
                {
                    "type": "missing_evidence",
                    "severity": Severity.ERROR.value,
                    "message": "No run evidence artifacts were found for compliance scoring",
                    "details": {
                        "expected_paths": [
                            "workspace/intermediates/pass_01/gaps.json",
                            "workspace/intermediates/pass_01/evidence.jsonl",
                        ]
                    },
                }
            )
            evidence_by_category = {
                "format": 0,
                "coverage": 0,
                "resolution": 0,
                "truncation": 0,
            }
            metrics = ComplianceMetrics(
                format_compliance=0.0,
                annotation_coverage=0.0,
                id_normalization=0.0,
                gate_threshold=max(0.0, 1.0 - self.blocker_threshold),
            )
        else:
            metrics, evidence_by_category = self._compute_metrics_from_evidence(evidence)
        base_score = (
            metrics.format_compliance + metrics.annotation_coverage + metrics.id_normalization
        ) / 3.0
        penalty = (len(blockers) * 0.10) + (len(warnings) * 0.02)
        score = max(0.0, base_score - penalty)

        details = {
            "format_compliance": metrics.format_compliance,
            "annotation_coverage": metrics.annotation_coverage,
            "id_normalization": metrics.id_normalization,
            "remainder_ratio": 0.0,
            "unresolved_references": 0,
            "low_confidence_mappings": 0,
            "evidence_by_category": evidence_by_category,
        }

        return ComplianceResult(
            score=score,
            blockers=blockers,
            warnings=warnings,
            passed=len(blockers) == 0,
            details=details,
            pass_num=pass_num,
        )

    def check_artifact_presence(self, spec_folder: Path) -> list[dict[str, Any]]:
        """Validate required artifacts exist."""
        blockers: list[dict[str, Any]] = []
        manifest_dir = spec_folder / "manifest"

        checks = [
            ("sections", manifest_dir / "sections", "*.sections.json"),
            ("atoms", manifest_dir / "atoms", "*.atoms.jsonl"),
            ("terms", manifest_dir / "terms", "*.terms.json"),
        ]

        for name, per_file_dir, pattern in checks:
            has_per_file = per_file_dir.exists() and any(per_file_dir.glob(pattern))
            if not has_per_file:
                expected_path = f"manifest/{name}/{pattern}"
                blockers.append(
                    {
                        "type": "missing_artifact",
                        "severity": Severity.ERROR.value,
                        "message": f"Missing {expected_path}",
                        "details": {"expected_path": expected_path},
                    }
                )

        return blockers

    def check_schema_validity(self, spec_folder: Path) -> list[dict[str, Any]]:
        """Validate artifact schemas for manifest JSONs."""
        blockers: list[dict[str, Any]] = []
        manifest_dir = spec_folder / "manifest"

        sections_files = sorted((manifest_dir / "sections").glob("*.sections.json"))
        atoms_files = sorted((manifest_dir / "atoms").glob("*.atoms.jsonl"))
        terms_files = sorted((manifest_dir / "terms").glob("*.terms.json"))

        blockers.extend(self._validate_sections_files(sections_files))
        blockers.extend(self._validate_atoms_files(atoms_files))
        blockers.extend(self._validate_terms_files(terms_files))

        return blockers

    def check_section_spans(self, spec_folder: Path) -> list[dict[str, Any]]:
        """Detect overlaps or holes in section spans."""
        blockers: list[dict[str, Any]] = []
        sections_dir = spec_folder / "manifest" / "sections"
        if not sections_dir.exists():
            return blockers

        for sections_file in sorted(sections_dir.glob("*.sections.json")):
            try:
                payload = json.loads(sections_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                blockers.append(
                    {
                        "type": "schema_invalid",
                        "severity": Severity.ERROR.value,
                        "message": f"Invalid sections JSON: {sections_file.name}",
                        "details": {"error": str(exc), "file": str(sections_file)},
                    }
                )
                continue

            if not isinstance(payload, dict) or "sections" not in payload:
                continue

            sections = payload.get("sections", [])
            if not isinstance(sections, list):
                continue

            spans = []
            for section in sections:
                if not isinstance(section, dict):
                    continue
                start = section.get("start_line")
                end = section.get("end_line")
                if isinstance(start, int) and isinstance(end, int):
                    spans.append((start, end, section.get("section_id")))

            spans.sort(key=lambda s: (s[0], s[1]))
            prev_end = None
            for start, end, section_id in spans:
                if prev_end is not None and start <= prev_end:
                    blockers.append(
                        {
                            "type": "section_overlap",
                            "severity": Severity.ERROR.value,
                            "message": f"Section span overlap in {sections_file.name}",
                            "details": {
                                "file": str(sections_file),
                                "section_id": section_id,
                                "start_line": start,
                                "end_line": end,
                            },
                        }
                    )
                if prev_end is not None and start > prev_end + 1:
                    blockers.append(
                        {
                            "type": "section_hole",
                            "severity": Severity.ERROR.value,
                            "message": f"Section span hole in {sections_file.name}",
                            "details": {
                                "file": str(sections_file),
                                "missing_start": prev_end + 1,
                                "missing_end": start - 1,
                            },
                        }
                    )
                prev_end = max(prev_end or 0, end)

            total_lines = payload.get("total_lines")
            if isinstance(total_lines, int) and prev_end is not None and prev_end < total_lines:
                blockers.append(
                    {
                        "type": "section_hole",
                        "severity": Severity.ERROR.value,
                        "message": f"Section span hole in {sections_file.name}",
                        "details": {
                            "file": str(sections_file),
                            "missing_start": prev_end + 1,
                            "missing_end": total_lines,
                        },
                    }
                )

        return blockers

    def _load_run_evidence(
        self, run_root: Path
    ) -> tuple[list[_EvidenceRecord], list[dict[str, Any]], list[dict[str, Any]]]:
        evidence: list[_EvidenceRecord] = []
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        pass_01_dir = run_root / "workspace" / "intermediates" / "pass_01"
        gaps_path = pass_01_dir / "gaps.json"
        evidence_jsonl_path = pass_01_dir / "evidence.jsonl"

        if gaps_path.exists():
            try:
                payload = json.loads(gaps_path.read_text(encoding="utf-8"))
                if not isinstance(payload, list):
                    raise TypeError("gaps.json must contain a JSON array")
                for gap in payload:
                    if not isinstance(gap, dict):
                        continue
                    severity = self._severity_value(gap.get("severity", Severity.WARNING.value))
                    gap_category = self._category_from_gap(gap)
                    base_message = str(gap.get("description") or gap.get("id") or "gap finding")
                    gap_details = {
                        "category": gap_category,
                        "gap_id": gap.get("id"),
                        "gap_type": gap.get("gap_type"),
                    }
                    gap_evidence = gap.get("evidence")
                    if isinstance(gap_evidence, list) and gap_evidence:
                        for item in gap_evidence:
                            if not isinstance(item, dict):
                                continue
                            item_details_raw = item.get("details")
                            item_details: dict[str, Any] = (
                                dict(item_details_raw) if isinstance(item_details_raw, dict) else {}
                            )
                            item_details.setdefault("category", gap_category)
                            invariant_family = item.get("invariant_family")
                            if isinstance(invariant_family, str):
                                item_details.setdefault("invariant_family", invariant_family)
                            item_details.setdefault("gap_type", gap.get("gap_type"))
                            evidence.append(
                                _EvidenceRecord(
                                    detector=str(item.get("detector") or "gap_synthesizer"),
                                    severity=severity,
                                    message=str(item.get("description") or base_message),
                                    details=item_details,
                                )
                            )
                    else:
                        evidence.append(
                            _EvidenceRecord(
                                detector="gap_synthesizer",
                                severity=severity,
                                message=base_message,
                                details=gap_details,
                            )
                        )
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                blockers.append(
                    {
                        "type": "evidence_unreadable",
                        "severity": Severity.ERROR.value,
                        "message": "Failed to load compliance evidence from gaps.json",
                        "details": {"file": str(gaps_path), "error": str(exc)},
                    }
                )

        if not evidence and evidence_jsonl_path.exists():
            try:
                with evidence_jsonl_path.open("r", encoding="utf-8") as handle:
                    for line_no, line in enumerate(handle, start=1):
                        stripped = line.strip()
                        if not stripped:
                            continue
                        payload = json.loads(stripped)
                        if not isinstance(payload, dict):
                            raise TypeError("evidence record must be a JSON object")
                        details_raw = payload.get("details")
                        details: dict[str, Any] = (
                            dict(details_raw) if isinstance(details_raw, dict) else {}
                        )
                        category = self._extract_category_from_payload(payload)
                        if category is not None:
                            details.setdefault("category", category)
                        invariant_family = payload.get("invariant_family")
                        if isinstance(invariant_family, str):
                            details.setdefault("invariant_family", invariant_family)
                        evidence.append(
                            _EvidenceRecord(
                                detector=str(payload.get("detector") or "pass_01_evidence"),
                                severity=self._infer_payload_severity(payload),
                                message=str(
                                    payload.get("description")
                                    or payload.get("message")
                                    or f"evidence line {line_no}"
                                ),
                                details=details,
                            )
                        )
            except (OSError, json.JSONDecodeError, TypeError) as exc:
                blockers.append(
                    {
                        "type": "evidence_unreadable",
                        "severity": Severity.ERROR.value,
                        "message": "Failed to load compliance evidence from evidence.jsonl",
                        "details": {"file": str(evidence_jsonl_path), "error": str(exc)},
                    }
                )

        return evidence, blockers, warnings

    def _compute_metrics_from_evidence(
        self, evidence: list[Evidence]
    ) -> tuple[ComplianceMetrics, dict[str, int]]:
        category_counts = {
            "format": 0,
            "coverage": 0,
            "resolution": 0,
            "truncation": 0,
        }
        errors = 0
        warnings = 0
        for item in evidence:
            severity = self._severity_value(item.severity)
            if severity == "error":
                errors += 1
            elif severity == "warning":
                warnings += 1
            if severity in {"error", "warning"}:
                category = self._extract_evidence_category(item)
                if category in category_counts:
                    category_counts[category] += 1
        penalty = (errors * 0.10) + (warnings * 0.02)
        score = max(0.0, 1.0 - penalty)

        return (
            ComplianceMetrics(
                format_compliance=score,
                annotation_coverage=score,
                id_normalization=score,
                gate_threshold=max(0.0, 1.0 - self.blocker_threshold),
            ),
            category_counts,
        )

    @staticmethod
    def _normalize_evidence_category(raw: str | None) -> str | None:
        if not isinstance(raw, str):
            return None
        lowered = raw.strip().lower()
        if lowered in {"format", "format_violation"}:
            return "format"
        if lowered in {"coverage", "coverage_failure"}:
            return "coverage"
        if lowered in {"resolution", "entity_resolution", "entity_resolution_failure"}:
            return "resolution"
        if lowered in {"truncation", "remainder", "membership_failure"}:
            return "truncation"
        return None

    @classmethod
    def _extract_evidence_category(cls, evidence: Evidence) -> str | None:
        details = getattr(evidence, "details", None)
        if isinstance(details, dict):
            category = details.get("category")
            if isinstance(category, str):
                normalized = cls._normalize_evidence_category(category)
                if normalized is not None:
                    return normalized
            invariant_family = details.get("invariant_family")
            if isinstance(invariant_family, str):
                normalized = cls._normalize_evidence_category(invariant_family)
                if normalized is not None:
                    return normalized
        detector = getattr(evidence, "detector", "")
        if isinstance(detector, str) and detector.startswith("strategy:"):
            candidate = detector.split(":", 1)[1]
            normalized = cls._normalize_evidence_category(candidate)
            if normalized is not None:
                return normalized
        message = getattr(evidence, "message", "")
        if isinstance(message, str) and ":" in message:
            candidate = message.split(":", 1)[0]
            normalized = cls._normalize_evidence_category(candidate)
            if normalized is not None:
                return normalized
        return None

    @staticmethod
    def _severity_value(severity: str | Severity | Any) -> str:
        if isinstance(severity, Severity):
            return severity.value
        normalized = str(severity).strip().lower()
        if normalized == "warn":
            return Severity.WARNING.value
        return normalized

    @classmethod
    def _category_from_gap(cls, gap: dict[str, Any]) -> str:
        gap_type = gap.get("gap_type")
        if isinstance(gap_type, str):
            normalized = cls._normalize_evidence_category(gap_type)
            if normalized is not None:
                return normalized
        for item in gap.get("evidence", []) if isinstance(gap.get("evidence"), list) else []:
            if isinstance(item, dict):
                category = cls._extract_category_from_payload(item)
                if category is not None:
                    return category
        return "resolution"

    @classmethod
    def _extract_category_from_payload(cls, payload: dict[str, Any]) -> str | None:
        details = payload.get("details")
        if isinstance(details, dict):
            category = details.get("category")
            if isinstance(category, str):
                normalized = cls._normalize_evidence_category(category)
                if normalized is not None:
                    return normalized
        invariant_family = payload.get("invariant_family")
        if isinstance(invariant_family, str):
            normalized = cls._normalize_evidence_category(invariant_family)
            if normalized is not None:
                return normalized
        detector = payload.get("detector")
        if isinstance(detector, str):
            normalized = cls._normalize_evidence_category(detector)
            if normalized is not None:
                return normalized
        return None

    @classmethod
    def _infer_payload_severity(cls, payload: dict[str, Any]) -> str:
        for key in ("severity",):
            value = payload.get(key)
            if value is not None:
                normalized = cls._severity_value(value)
                if normalized in {
                    Severity.ERROR.value,
                    Severity.WARNING.value,
                    Severity.INFO.value,
                }:
                    return normalized
        details = payload.get("details")
        if isinstance(details, dict):
            value = details.get("severity")
            if value is not None:
                normalized = cls._severity_value(value)
                if normalized in {
                    Severity.ERROR.value,
                    Severity.WARNING.value,
                    Severity.INFO.value,
                }:
                    return normalized
        return Severity.WARNING.value

    def _validate_sections_files(self, files: list[Path]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if not files:
            return blockers

        from spec_manager.schemas.sections import FileSections

        for path in files:
            try:
                payload = path.read_text(encoding="utf-8")
                FileSections.model_validate_json(payload)
            except Exception as exc:
                blockers.append(
                    {
                        "type": "schema_invalid",
                        "severity": Severity.ERROR.value,
                        "message": f"Schema invalid: {path.name}",
                        "details": {"error": str(exc), "file": str(path)},
                    }
                )
        return blockers

    def _validate_atoms_files(self, files: list[Path]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if not files:
            return blockers

        from spec_manager.schemas.atoms import LineAtom

        for path in files:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line_no, line in enumerate(handle, start=1):
                        stripped = line.strip()
                        if not stripped:
                            continue
                        try:
                            LineAtom.model_validate_json(stripped)
                        except Exception as exc:
                            blockers.append(
                                {
                                    "type": "schema_invalid",
                                    "severity": Severity.ERROR.value,
                                    "message": f"Schema invalid: {path.name}",
                                    "details": {
                                        "error": str(exc),
                                        "file": str(path),
                                        "line": line_no,
                                    },
                                }
                            )
                            break
            except OSError as exc:
                blockers.append(
                    {
                        "type": "schema_invalid",
                        "severity": Severity.ERROR.value,
                        "message": f"Schema invalid: {path.name}",
                        "details": {"error": str(exc), "file": str(path)},
                    }
                )
        return blockers

    def check_executable_gaps(
        self,
        spec_folder: Path,
        algorithmic_files: list[Path] | None = None,
    ) -> list[dict[str, Any]]:
        """Check for executable gaps that block promotion.

        Per design doc Section 12:
        - No remaining comments (all pseudocode translated) -> blocker
        - No stub functions (all atoms implemented) -> blocker

        Args:
            spec_folder: Path to the spec workspace.
            algorithmic_files: Optional explicit list of algorithmic code files.

        Returns:
            List of blocker dicts for compliance scoring.
        """
        from spec_manager.branches.gap_detection import scan_comments, scan_stubs

        blockers: list[dict[str, Any]] = []

        if algorithmic_files is None:
            return blockers

        total_comments = 0
        total_stubs = 0

        for filepath in algorithmic_files:
            from spec_manager.core.language import is_source_file

            if not filepath.exists() or not is_source_file(filepath.suffix):
                continue

            try:
                comments = scan_comments(filepath)
                total_comments += len(comments)
            except (OSError, UnicodeDecodeError) as exc:
                # C03: Surface errors — file read failure during compliance scan
                logger.warning("Failed to scan comments in %s", filepath, exc_info=True)
                blockers.append(
                    {
                        "type": "scan_unavailable",
                        "severity": Severity.ERROR.value,
                        "message": f"Failed to scan comments in {filepath}",
                        "details": {"file": str(filepath), "check": "comments", "error": str(exc)},
                    }
                )

            try:
                stubs = scan_stubs(filepath)
                total_stubs += len(stubs)
            except (OSError, UnicodeDecodeError) as exc:
                # C03: Surface errors — file read failure during compliance scan
                logger.warning("Failed to scan stubs in %s", filepath, exc_info=True)
                blockers.append(
                    {
                        "type": "scan_unavailable",
                        "severity": Severity.ERROR.value,
                        "message": f"Failed to scan stubs in {filepath}",
                        "details": {"file": str(filepath), "check": "stubs", "error": str(exc)},
                    }
                )

        if total_comments > 0:
            blockers.append(
                {
                    "type": "unimplemented_comments",
                    "severity": Severity.ERROR.value,
                    "message": (
                        f"{total_comments} unimplemented comments remain in algorithmic code"
                    ),
                    "details": {
                        "count": total_comments,
                        "files": [str(f) for f in algorithmic_files],
                    },
                }
            )

        if total_stubs > 0:
            blockers.append(
                {
                    "type": "stub_functions",
                    "severity": Severity.ERROR.value,
                    "message": (f"{total_stubs} stub functions remain in algorithmic code"),
                    "details": {
                        "count": total_stubs,
                        "files": [str(f) for f in algorithmic_files],
                    },
                }
            )

        return blockers

    def score_promotion_compliance(
        self,
        config: PromotionGateConfig,
        pin_registry: PinFunctionRegistry | None = None,
        provenance_registry_path: Path | None = None,
    ) -> ComplianceResult:
        """Score compliance for layer promotion.

        Creates a LayerPromotionGate, runs all checks, and converts
        the PromotionReport into a ComplianceResult for compatibility
        with the existing compliance pipeline.

        Args:
            config: Promotion gate configuration.
            pin_registry: PinFunctionRegistry (optional).
            provenance_registry_path: Path to provenance registry (optional).

        Returns:
            ComplianceResult with blockers/warnings from promotion gates.
        """
        from spec_manager.compliance.promotion.orchestrator import LayerPromotionGate
        from spec_manager.orchestration.evidence import EvidenceBundle

        evidence_bundle = EvidenceBundle(
            workspace_root=str(config.project_root),
            slice_root=str(config.project_root),
        )
        gate = LayerPromotionGate(
            config=config,
            evidence_bundle=evidence_bundle,
            pin_registry=pin_registry,
            provenance_registry_path=provenance_registry_path,
        )
        report = gate.run_all_checks()

        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        for blocker in report.blockers:
            blockers.append(
                {
                    "type": f"promotion_gate_{blocker.gate_id}",
                    "severity": Severity.ERROR.value,
                    "message": blocker.summary,
                    "details": {
                        "gate_id": blocker.gate_id,
                        "score": blocker.score,
                        "findings": blocker.findings,
                        "duration_ms": blocker.duration_ms,
                    },
                }
            )

        for warning in report.warnings:
            warnings.append(
                {
                    "type": f"promotion_gate_{warning.gate_id}",
                    "severity": Severity.WARNING.value,
                    "message": warning.summary,
                    "details": {
                        "gate_id": warning.gate_id,
                        "score": warning.score,
                        "findings": warning.findings,
                        "duration_ms": warning.duration_ms,
                    },
                }
            )

        # Compute average score across all gate results
        if report.gate_results:
            avg_score = sum(r.score for r in report.gate_results) / len(report.gate_results)
        else:
            avg_score = 1.0

        return ComplianceResult(
            score=avg_score,
            blockers=blockers,
            warnings=warnings,
            passed=report.passed,
            details={
                "promotion_report": report.to_dict(),
                "total_duration_ms": report.total_duration_ms,
            },
        )

    def _validate_terms_files(self, files: list[Path]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if not files:
            return blockers

        from spec_manager.schemas.terms import FileTerms

        for path in files:
            try:
                payload = path.read_text(encoding="utf-8")
                FileTerms.model_validate_json(payload)
            except Exception as exc:
                blockers.append(
                    {
                        "type": "schema_invalid",
                        "severity": Severity.ERROR.value,
                        "message": f"Schema invalid: {path.name}",
                        "details": {"error": str(exc), "file": str(path)},
                    }
                )
        return blockers
