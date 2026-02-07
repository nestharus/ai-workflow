"""Compliance scoring and gate evaluation for spec processing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from spec_manager.core.data_structures import ComplianceMetrics
from spec_manager.core.gaps import Severity

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

        metrics, evidence_by_category = self._compute_metrics_from_evidence([])
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
            ("sections", manifest_dir / "sections", "manifest/sections.json"),
            ("atoms", manifest_dir / "atoms", "manifest/atoms.jsonl"),
            ("terms", manifest_dir / "terms", "manifest/terms.json"),
        ]

        for name, per_file_dir, legacy_path in checks:
            has_per_file = per_file_dir.exists() and any(per_file_dir.glob(f"*.{name}.json*"))
            has_legacy = (spec_folder / legacy_path).exists()
            if not has_per_file and not has_legacy:
                blockers.append(
                    {
                        "type": "missing_artifact",
                        "severity": Severity.ERROR.value,
                        "message": f"Missing {legacy_path}",
                        "details": {"expected_path": legacy_path},
                    }
                )

        return blockers

    def check_schema_validity(self, spec_folder: Path) -> list[dict[str, Any]]:
        """Validate artifact schemas for manifest JSONs."""
        blockers: list[dict[str, Any]] = []
        manifest_dir = spec_folder / "manifest"

        sections_files = self._resolve_artifacts(
            manifest_dir / "sections",
            manifest_dir / "sections.json",
            "*.sections.json",
        )
        atoms_files = self._resolve_artifacts(
            manifest_dir / "atoms",
            manifest_dir / "atoms.jsonl",
            "*.atoms.jsonl",
        )
        terms_files = self._resolve_artifacts(
            manifest_dir / "terms",
            manifest_dir / "terms.json",
            "*.terms.json",
        )

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
    def _extract_evidence_category(evidence: Evidence) -> str | None:
        detector = getattr(evidence, "detector", "")
        if not isinstance(detector, str) or not detector.startswith("strategy:"):
            return None
        details = getattr(evidence, "details", None)
        if isinstance(details, dict):
            category = details.get("category")
            if isinstance(category, str):
                return category
        message = getattr(evidence, "message", "")
        if isinstance(message, str) and ":" in message:
            candidate = message.split(":", 1)[0]
            return candidate
        return None

    @staticmethod
    def _severity_value(severity: str | Severity) -> str:
        if isinstance(severity, Severity):
            return severity.value
        return str(severity)

    @staticmethod
    def _resolve_artifacts(
        per_file_dir: Path,
        legacy_file: Path,
        pattern: str,
    ) -> list[Path]:
        if per_file_dir.exists():
            per_file = sorted(per_file_dir.glob(pattern))
            if per_file:
                return per_file
        if legacy_file.exists():
            return [legacy_file]
        return []

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
        from spec_manager.compliance.detection.comment_scanner import scan_comments
        from spec_manager.compliance.detection.stub_scanner import scan_stubs

        blockers: list[dict[str, Any]] = []

        if algorithmic_files is None:
            return blockers

        total_comments = 0
        total_stubs = 0

        for filepath in algorithmic_files:
            if not filepath.exists() or filepath.suffix != ".py":
                continue

            try:
                comments = scan_comments(filepath)
                total_comments += len(comments)
            except (OSError, UnicodeDecodeError):
                pass

            try:
                stubs = scan_stubs(filepath)
                total_stubs += len(stubs)
            except (OSError, UnicodeDecodeError):
                pass

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

        gate = LayerPromotionGate(
            config=config,
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
