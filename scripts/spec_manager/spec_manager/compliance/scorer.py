"""Compliance scoring and gate evaluation for spec processing."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from spec_manager.core.data_structures import ComplianceMetrics
from spec_manager.core.gaps import Severity
from spec_manager.workspace.state import WorkspaceState

if TYPE_CHECKING:
    from spec_manager.workflow.orchestrator import WorkflowEvidence


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
        self.blocker_threshold = blocker_threshold
        self.warning_threshold = warning_threshold
        self._previous_state: WorkspaceState | None = None

    def score_compliance(
        self,
        evidence: list["WorkflowEvidence"],
        state: WorkspaceState,
        spec_folder: Path,
    ) -> ComplianceResult:
        """Score compliance using evidence, workspace state, and artifacts."""
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        blockers.extend(self.check_artifact_presence(spec_folder))
        blockers.extend(self.check_schema_validity(spec_folder))
        blockers.extend(self.check_section_spans(spec_folder))
        blockers.extend(self.check_regressions(state, self._previous_state))

        remainder_ratio = self._compute_remainder_ratio(state)
        unresolved_references = self._count_unresolved_references(evidence)
        low_confidence = self._count_low_confidence_mappings(state)

        if remainder_ratio > self.warning_threshold:
            warnings.append(
                {
                    "type": "high_remainder_ratio",
                    "severity": Severity.WARNING.value,
                    "message": (
                        f"Remainder ratio {remainder_ratio:.1%} exceeds threshold "
                        f"{self.warning_threshold:.1%}"
                    ),
                    "details": {"ratio": remainder_ratio, "threshold": self.warning_threshold},
                }
            )

        if unresolved_references:
            warnings.append(
                {
                    "type": "unresolved_references",
                    "severity": Severity.WARNING.value,
                    "message": f"{unresolved_references} unresolved references detected",
                    "details": {"count": unresolved_references},
                }
            )

        if low_confidence:
            warnings.append(
                {
                    "type": "low_confidence_mappings",
                    "severity": Severity.WARNING.value,
                    "message": f"{low_confidence} low-confidence mappings detected",
                    "details": {
                        "count": low_confidence,
                        "threshold": self.warning_threshold,
                    },
                }
            )

        metrics = self._compute_metrics_from_evidence(evidence)
        score = (
            metrics.format_compliance + metrics.annotation_coverage + metrics.id_normalization
        ) / 3.0

        details = {
            "format_compliance": metrics.format_compliance,
            "annotation_coverage": metrics.annotation_coverage,
            "id_normalization": metrics.id_normalization,
            "remainder_ratio": remainder_ratio,
            "unresolved_references": unresolved_references,
            "low_confidence_mappings": low_confidence,
        }

        result = ComplianceResult(
            score=score,
            blockers=blockers,
            warnings=warnings,
            passed=len(blockers) == 0,
            details=details,
        )

        self._previous_state = copy.deepcopy(state)
        return result

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

    def check_regressions(
        self,
        current_state: WorkspaceState,
        previous_state: WorkspaceState | None,
    ) -> list[dict[str, Any]]:
        """Detect regressions between passes."""
        if previous_state is None:
            return []

        blockers: list[dict[str, Any]] = []

        current_ids = self._collect_unit_ids(current_state)
        previous_ids = self._collect_unit_ids(previous_state)
        lost_ids = sorted(previous_ids - current_ids)
        if lost_ids:
            blockers.append(
                {
                    "type": "regression_lost_ids",
                    "severity": Severity.ERROR.value,
                    "message": f"Lost {len(lost_ids)} unit IDs since previous pass",
                    "details": {"count": len(lost_ids), "sample": lost_ids[:10]},
                }
            )

        current_atoms = self._collect_atom_ids(current_state)
        previous_atoms = self._collect_atom_ids(previous_state)
        lost_atoms = sorted(previous_atoms - current_atoms)
        if lost_atoms:
            blockers.append(
                {
                    "type": "regression_lost_atoms",
                    "severity": Severity.ERROR.value,
                    "message": f"Lost {len(lost_atoms)} atom IDs since previous pass",
                    "details": {"count": len(lost_atoms), "sample": lost_atoms[:10]},
                }
            )

        return blockers

    def _compute_metrics_from_evidence(self, evidence: list["WorkflowEvidence"]) -> ComplianceMetrics:
        errors = sum(1 for e in evidence if self._severity_value(e.severity) == "error")
        warnings = sum(1 for e in evidence if self._severity_value(e.severity) == "warning")
        penalty = (errors * 0.10) + (warnings * 0.02)
        score = max(0.0, 1.0 - penalty)

        return ComplianceMetrics(
            format_compliance=score,
            annotation_coverage=score,
            id_normalization=score,
            gate_threshold=max(0.0, 1.0 - self.blocker_threshold),
        )

    @staticmethod
    def _severity_value(severity: str | Severity) -> str:
        if isinstance(severity, Severity):
            return severity.value
        return str(severity)

    @staticmethod
    def _compute_remainder_ratio(state: WorkspaceState) -> float:
        units = getattr(state, "units", [])
        remainders = getattr(state, "remainders", [])
        return len(remainders) / max(len(units), 1)

    @staticmethod
    def _count_unresolved_references(evidence: list["WorkflowEvidence"]) -> int:
        return sum(
            1
            for e in evidence
            if getattr(e, "detector", "") == "undefined_reference"
        )

    def _count_low_confidence_mappings(self, state: WorkspaceState) -> int:
        final_labels = getattr(state, "final_labels", {})
        count = 0
        if isinstance(final_labels, dict):
            for value in final_labels.values():
                confidence = getattr(value, "confidence", None)
                if confidence is None and isinstance(value, dict):
                    confidence = value.get("confidence")
                if isinstance(confidence, (int, float)) and confidence < self.warning_threshold:
                    count += 1
        return count

    @staticmethod
    def _collect_unit_ids(state: WorkspaceState) -> set[str]:
        ids: set[str] = set()
        for unit in getattr(state, "units", []):
            unit_id = getattr(unit, "id", None)
            if unit_id:
                ids.add(str(unit_id))
        return ids

    @staticmethod
    def _collect_atom_ids(state: WorkspaceState) -> set[str]:
        atom_ids: set[str] = set()
        units = list(getattr(state, "units", [])) + list(getattr(state, "remainders", []))
        for unit in units:
            for atom_id in getattr(unit, "source_atom_ids", []) or []:
                if atom_id:
                    atom_ids.add(str(atom_id))
        return atom_ids

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

        from scripts.spec_refinement.schemas.sections import FileSections

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

        from scripts.spec_refinement.schemas.atoms import LineAtom

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

    def _validate_terms_files(self, files: list[Path]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if not files:
            return blockers

        from scripts.spec_refinement.schemas.terms import FileTerms

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
