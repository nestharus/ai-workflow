"""Promotion gate orchestrator."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.compliance.promotion.algorithmic_gates import (
    check_all_tests_pass,
    check_call_graph_connected,
    check_no_remaining_comments,
    check_no_stub_functions,
    check_store_monogamy,
)
from spec_manager.compliance.promotion.architectural_quality import (
    check_arch_drift_pass,
    check_config_externalization,
    check_edge_realization,
    check_event_handler_coverage,
    check_function_recomposition,
    check_no_inlined_atom_logic,
    check_no_orphan_components,
    check_pin_consumption_coverage,
)
from spec_manager.compliance.promotion.config import (
    GateId,
    GateMode,
    GateSpec,
    PromotionGateConfig,
)
from spec_manager.compliance.promotion.introduction_checker import (
    check_introduced_algorithm_specs,
)
from spec_manager.compliance.promotion.pin_coverage import (
    PinCoverageReport,
    build_pin_coverage_report,
    check_pin_coverage,
)
from spec_manager.compliance.promotion.provenance import (
    ProvenanceRegistry,
    check_provenance_complete,
)
from spec_manager.compliance.promotion.result import (
    GateCheckResult,
    GateStatus,
    PromotionReport,
)
from spec_manager.compliance.promotion.test_pin_gate import (
    check_test_pin_alignment_gate,
)
from spec_manager.schemas.pin_functions import PinFunctionRegistry

if TYPE_CHECKING:
    from spec_manager.branches.atoms import AtomRegistry
    from spec_manager.core.evidence_index import EvidenceIndex
    from spec_manager.schemas.entities import EntitiesArtifact


class LayerPromotionGate:
    """Orchestrates all promotion gate checks."""

    def __init__(
        self,
        config: PromotionGateConfig,
        pin_registry: PinFunctionRegistry | None = None,
        graph_snapshot: dict[str, Any] | None = None,
        pins_snapshot: dict[str, Any] | None = None,
        provenance_registry_path: Path | None = None,
        evidence_index: EvidenceIndex | None = None,
        entities_artifact: EntitiesArtifact | None = None,
        algorithmic_analyzed: list[Any] | None = None,
        architectural_analyzed: list[Any] | None = None,
        gap_inventory: list[dict[str, Any]] | None = None,
        component_manifest_path: Path | None = None,
    ) -> None:
        self._config = config
        self._pin_registry = pin_registry
        self._graph_snapshot = graph_snapshot or {}
        self._pins_snapshot = pins_snapshot or {}
        self._provenance_registry_path = provenance_registry_path
        self._evidence_index = evidence_index
        self._entities_artifact = entities_artifact
        self._project_root = Path(config.project_root)
        self._algorithmic_analyzed = algorithmic_analyzed
        self._architectural_analyzed = architectural_analyzed
        self._gap_inventory = gap_inventory
        self._component_manifest_path_override = component_manifest_path

    def run_all_checks(self) -> PromotionReport:
        """Run all enabled gate checks and produce a promotion report."""
        start = time.monotonic()
        algorithmic_files = self._resolve_algorithmic_files()
        architectural_files = self._resolve_architectural_files()

        component_manifest_path, component_manifest = self._load_component_manifest()
        pin_coverage_report: PinCoverageReport | None = None

        results: list[GateCheckResult] = []
        for gate_id in GateId:
            gate_spec = self._config.get_gate(gate_id)
            if not gate_spec.enabled:
                continue
            result, pin_coverage_report = self._execute_gate(
                gate_id=gate_id,
                gate_spec=gate_spec,
                algorithmic_files=algorithmic_files,
                architectural_files=architectural_files,
                component_manifest_path=component_manifest_path,
                component_manifest=component_manifest,
                pin_coverage_report=pin_coverage_report,
            )
            results.append(result)

        total_duration = (time.monotonic() - start) * 1000
        return self._build_report(results, total_duration)

    def run_single_check(self, gate_id: GateId) -> GateCheckResult:
        """Run a single gate check by ID."""
        gate_spec = self._config.get_gate(gate_id)
        algorithmic_files = self._resolve_algorithmic_files()
        architectural_files = self._resolve_architectural_files()
        component_manifest_path, component_manifest = self._load_component_manifest()

        result, _ = self._execute_gate(
            gate_id=gate_id,
            gate_spec=gate_spec,
            algorithmic_files=algorithmic_files,
            architectural_files=architectural_files,
            component_manifest_path=component_manifest_path,
            component_manifest=component_manifest,
            pin_coverage_report=None,
        )
        return result

    def _execute_gate(
        self,
        *,
        gate_id: GateId,
        gate_spec: GateSpec,
        algorithmic_files: list[Path],
        architectural_files: list[Path],
        component_manifest_path: Path | None,
        component_manifest: dict[str, Any] | None,
        pin_coverage_report: PinCoverageReport | None,
    ) -> tuple[GateCheckResult, PinCoverageReport | None]:
        """Dispatch one gate execution."""
        if gate_id == GateId.NO_REMAINING_COMMENTS:
            return (
                check_no_remaining_comments(
                    algorithmic_files,
                    gate_spec,
                    analyzed=self._algorithmic_analyzed,
                    gap_inventory=self._gap_inventory,
                ),
                pin_coverage_report,
            )

        if gate_id == GateId.NO_STUB_FUNCTIONS:
            return (
                check_no_stub_functions(
                    algorithmic_files,
                    gate_spec,
                    analyzed=self._algorithmic_analyzed,
                ),
                pin_coverage_report,
            )

        if gate_id == GateId.ALL_TESTS_PASS:
            return (
                check_all_tests_pass(self._config.test_command, self._project_root, gate_spec),
                pin_coverage_report,
            )

        if gate_id == GateId.CALL_GRAPH_CONNECTED:
            return (
                check_call_graph_connected(
                    algorithmic_files,
                    self._project_root,
                    gate_spec,
                    analyzed=self._algorithmic_analyzed,
                ),
                pin_coverage_report,
            )

        if gate_id == GateId.STORE_MONOGAMY:
            return (
                check_store_monogamy(
                    algorithmic_files,
                    self._project_root,
                    gate_spec,
                    analyzed=self._algorithmic_analyzed,
                ),
                pin_coverage_report,
            )

        if gate_id == GateId.PIN_COVERAGE:
            if self._pin_registry is None:
                return (
                    self._missing_evidence_gate(
                        gate_id,
                        gate_spec,
                        "PinFunctionRegistry not provided",
                    ),
                    pin_coverage_report,
                )
            result = check_pin_coverage(
                self._pin_registry,
                architectural_files,
                gate_spec,
                analyzed=self._architectural_analyzed,
            )
            pin_coverage_report = build_pin_coverage_report(
                self._pin_registry,
                architectural_files,
                analyzed=self._architectural_analyzed,
            )
            return result, pin_coverage_report

        if gate_id == GateId.INTRODUCED_ALGORITHM_SPECS:
            if self._pin_registry is None:
                return (
                    self._missing_evidence_gate(
                        gate_id,
                        gate_spec,
                        "PinFunctionRegistry not provided",
                    ),
                    pin_coverage_report,
                )
            if pin_coverage_report is None:
                pin_coverage_report = build_pin_coverage_report(
                    self._pin_registry,
                    architectural_files,
                    analyzed=self._architectural_analyzed,
                )
            return (
                check_introduced_algorithm_specs(
                    pin_coverage_report,
                    architectural_files,
                    gate_spec,
                    analyzed=self._architectural_analyzed,
                ),
                pin_coverage_report,
            )

        if gate_id == GateId.NO_INLINED_ATOM_LOGIC:
            if self._pin_registry is None:
                return (
                    self._missing_evidence_gate(
                        gate_id,
                        gate_spec,
                        "PinFunctionRegistry not provided",
                    ),
                    pin_coverage_report,
                )
            return (
                check_no_inlined_atom_logic(
                    self._pin_registry,
                    architectural_files,
                    algorithmic_files,
                    gate_spec,
                    analyzed_arch=self._architectural_analyzed,
                    analyzed_algo=self._algorithmic_analyzed,
                ),
                pin_coverage_report,
            )

        if gate_id == GateId.FUNCTION_RECOMPOSITION:
            if self._pin_registry is None:
                return (
                    self._missing_evidence_gate(
                        gate_id,
                        gate_spec,
                        "PinFunctionRegistry not provided",
                    ),
                    pin_coverage_report,
                )
            return (
                check_function_recomposition(
                    self._pin_registry,
                    architectural_files,
                    gate_spec,
                    analyzed_arch=self._architectural_analyzed,
                ),
                pin_coverage_report,
            )

        if gate_id == GateId.PIN_CONSUMPTION_COVERAGE:
            if self._pin_registry is None:
                return (
                    self._missing_evidence_gate(
                        gate_id,
                        gate_spec,
                        "PinFunctionRegistry not provided",
                    ),
                    pin_coverage_report,
                )
            if component_manifest is None:
                return (
                    self._missing_evidence_gate(
                        gate_id,
                        gate_spec,
                        "Component manifest not provided",
                    ),
                    pin_coverage_report,
                )
            return (
                check_pin_consumption_coverage(self._pin_registry, component_manifest, gate_spec),
                pin_coverage_report,
            )

        if gate_id == GateId.EDGE_REALIZATION:
            if component_manifest is None:
                return (
                    self._missing_evidence_gate(
                        gate_id,
                        gate_spec,
                        "Component manifest not provided",
                    ),
                    pin_coverage_report,
                )
            return check_edge_realization(component_manifest, gate_spec), pin_coverage_report

        if gate_id == GateId.NO_ORPHAN_COMPONENTS:
            if component_manifest is None:
                return (
                    self._missing_evidence_gate(
                        gate_id,
                        gate_spec,
                        "Component manifest not provided",
                    ),
                    pin_coverage_report,
                )
            return check_no_orphan_components(component_manifest, gate_spec), pin_coverage_report

        if gate_id == GateId.EVENT_HANDLER_COVERAGE:
            if component_manifest is None:
                return (
                    self._missing_evidence_gate(
                        gate_id,
                        gate_spec,
                        "Component manifest not provided",
                    ),
                    pin_coverage_report,
                )
            return check_event_handler_coverage(component_manifest, gate_spec), pin_coverage_report

        if gate_id == GateId.CONFIG_EXTERNALIZATION:
            return (
                check_config_externalization(
                    architectural_files,
                    gate_spec,
                    analyzed_arch=self._architectural_analyzed,
                ),
                pin_coverage_report,
            )

        if gate_id == GateId.ARCH_DRIFT_PASS:
            return check_arch_drift_pass(component_manifest_path, gate_spec), pin_coverage_report

        if gate_id == GateId.PROVENANCE_COMPLETE:
            if self._pin_registry is None:
                return (
                    self._missing_evidence_gate(
                        gate_id,
                        gate_spec,
                        "PinFunctionRegistry not provided",
                    ),
                    pin_coverage_report,
                )
            return (
                check_provenance_complete(
                    self._pin_registry,
                    self._load_provenance(),
                    gate_spec,
                ),
                pin_coverage_report,
            )

        if gate_id == GateId.ENTITY_COVERAGE:
            return self._run_entity_coverage(gate_spec), pin_coverage_report

        if gate_id == GateId.TEST_PIN_ALIGNMENT:
            return self._run_test_pin_alignment(gate_spec), pin_coverage_report

        return self._not_implemented_gate(gate_id, gate_spec), pin_coverage_report

    def _run_test_pin_alignment(self, gate_spec: GateSpec) -> GateCheckResult:
        if self._pin_registry is None:
            return self._missing_evidence_gate(
                GateId.TEST_PIN_ALIGNMENT,
                gate_spec,
                "PinFunctionRegistry not provided",
            )
        test_roots = [
            self._project_root / root for root in gate_spec.params.get("test_roots", ["tests/"])
        ]
        baseline_path = self._project_root / ".spec" / "test_pin_baselines.json"
        return check_test_pin_alignment_gate(
            self._pin_registry,
            test_roots,
            baseline_path,
            gate_spec,
        )

    def _run_entity_coverage(self, gate_spec: GateSpec) -> GateCheckResult:
        if self._evidence_index is None:
            return self._missing_evidence_gate(
                GateId.ENTITY_COVERAGE,
                gate_spec,
                "EvidenceIndex not provided",
            )

        from spec_manager.compliance.coverage.gate import check_entity_coverage

        return check_entity_coverage(
            self._evidence_index,
            self._atom_registry_for_coverage(),
            gate_spec,
            self._entities_artifact,
        )

    def _resolve_algorithmic_files(self) -> list[Path]:
        """Resolve algorithmic files from snapshots first, then roots."""
        snapshot_files = self._collect_files_from_pins_snapshot()
        if snapshot_files:
            return snapshot_files
        return self._resolve_files(self._config.algorithmic_roots)

    def _resolve_architectural_files(self) -> list[Path]:
        """Resolve architectural files from snapshots first, then roots."""
        snapshot_files = self._collect_files_from_graph_snapshot()
        if snapshot_files:
            return snapshot_files
        return self._resolve_files(self._config.architectural_roots)

    def _collect_files_from_pins_snapshot(self) -> list[Path]:
        """Collect algorithmic file paths from a pins snapshot payload."""
        payload = self._pins_snapshot if isinstance(self._pins_snapshot, dict) else {}
        pins = payload.get("pins")
        if not isinstance(pins, list):
            return []

        files: list[Path] = []
        seen: set[str] = set()
        for pin in pins:
            if not isinstance(pin, dict):
                continue
            candidate = pin.get("file_path") or pin.get("file")
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            resolved = (self._project_root / candidate).resolve()
            if not resolved.is_file():
                continue
            key = resolved.as_posix()
            if key in seen:
                continue
            seen.add(key)
            files.append(resolved)
        return files

    def _collect_files_from_graph_snapshot(self) -> list[Path]:
        """Collect architectural file paths from a graph snapshot payload."""
        payload = self._graph_snapshot if isinstance(self._graph_snapshot, dict) else {}
        edges = payload.get("edges")
        if not isinstance(edges, list):
            return []

        files: list[Path] = []
        seen: set[str] = set()
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            candidate = edge.get("arch_file_path")
            if not isinstance(candidate, str) or not candidate.strip():
                raw_dst = edge.get("dst")
                if isinstance(raw_dst, str) and ":" in raw_dst:
                    candidate = raw_dst.split(":", 1)[0]
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            resolved = (self._project_root / candidate).resolve()
            if not resolved.is_file():
                continue
            key = resolved.as_posix()
            if key in seen:
                continue
            seen.add(key)
            files.append(resolved)
        return files

    def _atom_registry_for_coverage(self) -> AtomRegistry:
        from spec_manager.branches.atoms import AtomRegistry as _AtomRegistry
        from spec_manager.branches.layout import BranchLayout

        layout = BranchLayout(run_root=self._project_root)
        return _AtomRegistry(layout)

    def _load_provenance(self) -> ProvenanceRegistry:
        if self._provenance_registry_path:
            return ProvenanceRegistry.load(self._provenance_registry_path)
        return ProvenanceRegistry()

    def _resolve_files(self, roots: list[str]) -> list[Path]:
        from spec_manager.core.language import source_rglob

        files: list[Path] = []
        for root in roots:
            root_path = self._project_root / root
            if root_path.exists():
                files.extend(source_rglob(root_path))
        return files

    def _load_component_manifest(self) -> tuple[Path | None, dict[str, Any] | None]:
        """Load component manifest from explicit path or run reports."""
        path = self._component_manifest_path_override
        if path is None:
            direct = self._project_root / "component_manifest.json"
            if direct.exists():
                path = direct
            else:
                report_candidates = sorted(
                    (self._project_root / "reports" / "pdd").glob("*/component_manifest.json"),
                    key=lambda item: item.stat().st_mtime,
                    reverse=True,
                )
                if report_candidates:
                    path = report_candidates[0]

        if path is None or not path.exists():
            return None, None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return path, None

        if not isinstance(payload, dict):
            return path, None
        return path, payload

    @staticmethod
    def _missing_evidence_gate(
        gate_id: GateId,
        gate_spec: GateSpec,
        reason: str,
    ) -> GateCheckResult:
        return GateCheckResult(
            gate_id=gate_id.value,
            mode=GateMode.ADVISORY.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": reason, "configured_mode": gate_spec.mode.value}],
            summary=f"Gate blocked by missing evidence: {reason}",
            duration_ms=0.0,
        )

    @staticmethod
    def _not_implemented_gate(gate_id: GateId, gate_spec: GateSpec) -> GateCheckResult:
        return GateCheckResult(
            gate_id=gate_id.value,
            mode=GateMode.ADVISORY.value,
            status=GateStatus.AMBIGUOUS,
            score=0.0,
            findings=[{"reason": "gate_not_implemented", "configured_mode": gate_spec.mode.value}],
            summary=f"Gate '{gate_id.value}' is not implemented",
            duration_ms=0.0,
        )

    @staticmethod
    def _build_report(results: list[GateCheckResult], total_duration_ms: float) -> PromotionReport:
        blockers: list[GateCheckResult] = []
        warnings: list[GateCheckResult] = []

        for result in results:
            if result.passed:
                continue
            if result.mode == GateMode.REQUIRED.value:
                blockers.append(result)
            else:
                warnings.append(result)

        return PromotionReport(
            passed=len(blockers) == 0,
            gate_results=results,
            blockers=blockers,
            warnings=warnings,
            total_duration_ms=total_duration_ms,
        )
