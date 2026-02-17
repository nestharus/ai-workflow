# TODO(single-layer): RESTRUCTURE — Gate orchestrator reorganizes from layer gates to
#   aspect gates (Section 10). Three gate groups replace the current mix:
#   A) Behavior gates (hard): ALL_TESTS_PASS, contract verifier tests, no under-spec blocks
#   B) Architecture gates (hard where deterministic): import boundary per shape, shape drift
#   C) Quality gates (hard only if deterministic): formatter/linter/static;
#     non-deterministic quality checks route to work items + optional human approval
#     instead of hard gating (Section 10.1 fallback)
#   DELETE: All PIN_* gates, ARCH_DRIFT_PASS (pin-registry drift), NO_INLINED_ATOM_LOGIC
#   KEEP: ALL_TESTS_PASS (primary authority), check_no_remaining_comments (if adapted)
#   CONVERT to soft: CALL_GRAPH_CONNECTED (routing signal), NO_STUB_FUNCTIONS
#   Section 10.2 has the complete mapping.
#   Non-ship enforcement (Section 15): if key structural contracts cannot be
#   verifier-backed, gate orchestrator must emit a hard-stop / do-not-ship decision.
#   Deterministic authority boundary (Section 13.1): gate orchestrator must only use
#   deterministic evidence (test results, import scans, file diffs, shape doc parsing,
#   manifests, config parsing) for convergence checks. LLM outputs are advisory only —
#   never determine pass/fail of hard gates.
# ALGORITHM(single-layer):
#   References: response3 Sections 10.1, 10.2, 13.1, 15.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] — three-phase forward-only pipeline.
#     - AspectGateGroup = Literal['behavior', 'architecture', 'quality']
#     - AspectGatePlan: {group: AspectGateGroup, gate_ids: list[GateId], hard_required: bool}
#     - GateRunContext: {shape_reports: dict[ShapeId, ShapeMatchReport], verifier_summaries: dict[ShapeId, VerifierRunSummary], evidence_bundle: EvidenceBundle}
# IMPL(single-layer): Gate context consumes verifier summaries keyed by shape;
# pass/fail authority comes from ACTIVE-shape verifier outcomes, not proposal diagnostics.
#   Interface contracts:
#     - class AspectPromotionGate: run_all_checks() -> PromotionReport
#     - def run_group(self, group: AspectGateGroup, ctx: GateRunContext) -> list[GateCheckResult]
#     - def evaluate_non_ship(self, ctx: GateRunContext) -> GateCheckResult
#   Control flow:
#     1. Three phases (Libraries -> Architecture -> Quality), forward-only, no cycling back.
#     2. Each phase edits code via its own PromotionLoop with IMPLEMENT step.
#     3. Each phase is its own cycle with bounded iterations per slice.
#     4. Build gate plan by aspect group, removing PIN_* and layer-only gates.
#     5. Libraries phase gates: library verifiers (hard) + LLM gap scans (soft).
#     6. Architecture phase gates: shape matching + contract verifiers + integration tests (hard) + L2 reviewers (soft).
#        Import boundary check + shape drift resolved from matcher reports.
# IMPL(single-layer): Keep Architecture-group dispatch aligned with
# `architectural_quality` migration: once `check_import_boundary_per_shape` and
# `check_shape_drift_resolved` exist, they become the hard structural gates and
# legacy pin-era architecture gates (`NO_INLINED_ATOM_LOGIC`,
# `PIN_CONSUMPTION_COVERAGE`, `EDGE_REALIZATION`, `ARCH_DRIFT_PASS`) should not be
# scheduled.
#     7. Quality phase gates: all tests + contract verifiers + style checks (hard) + quality reviewers (soft).
#        Deterministic formatter/lint/static checks only; non-deterministic findings become advisory work items.
#     8. Merge results into PromotionReport and set overall pass only if all required hard gates pass.
#     9. Enforce non-ship hard stop when critical contracts lack verifier backing (Section 15).
# IMPL(single-layer): Non-ship evaluation should consume
# `routing.verifiers.enforce_non_ship_policy` output directly; `non_ship_block=True`
# is a terminal hard-stop signal.
#     10. No backtracking: phases block if outside their authority; phase-local remediation if within authority.
#   Error handling:
#     - Missing deterministic inputs yields STALE_EVIDENCE failed gate, never silent pass.
#     - LLM-only evidence is ignored for hard pass/fail.
#   Integration points:
#     - Called by promotion loop PROMOTE step and lifecycle termination checks.
#     - Calls algorithmic_gates (Libraries phase), architectural_quality (Architecture phase), routing verifiers/matcher.
# IMPL(single-layer): Libraries behavior-group orchestration should treat
# `check_call_graph_connected`/`check_no_stub_functions` (and store-monogamy when
# non-deterministic) as advisory defaults, with blocking controlled by GateSpec mode.
#   Test requirements:
#     - Group composition and required/advisory behavior.
#     - Non-ship trigger on missing critical verifiers.
#     - LLM advisory findings do not flip hard gate status.
#     - Phase forward-only ordering enforced (no backtracking).

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
from spec_manager.orchestration.evidence import EvidenceBundle
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
        evidence_bundle: EvidenceBundle,
        pin_registry: PinFunctionRegistry | None = None,
        provenance_registry_path: Path | None = None,
        evidence_index: EvidenceIndex | None = None,
        entities_artifact: EntitiesArtifact | None = None,
        algorithmic_analyzed: list[Any] | None = None,
        architectural_analyzed: list[Any] | None = None,
        component_manifest_path: Path | None = None,
    ) -> None:
        self._config = config
        self._bundle = evidence_bundle
        self._pin_registry = pin_registry
        self._provenance_registry_path = provenance_registry_path
        self._evidence_index = evidence_index
        self._entities_artifact = entities_artifact
        self._project_root = Path(config.project_root)
        self._algorithmic_analyzed = algorithmic_analyzed
        self._architectural_analyzed = architectural_analyzed
        self._component_manifest_path_override = component_manifest_path
        self._snapshot_load_failures: list[dict[str, Any]] = []

    def run_all_checks(self) -> PromotionReport:
        """Run all enabled gate checks and produce a promotion report."""
        start = time.monotonic()
        self._snapshot_load_failures = []
        algorithmic_files = self._resolve_algorithmic_files()
        architectural_files = self._resolve_architectural_files()

        component_manifest_path, component_manifest = self._load_component_manifest()
        pin_coverage_report: PinCoverageReport | None = None

        results: list[GateCheckResult] = []
        for gate_id in GateId:
            gate_spec = self._config.get_gate(gate_id)
            if not gate_spec.enabled:
                continue
            try:
                result, pin_coverage_report = self._execute_gate(
                    gate_id=gate_id,
                    gate_spec=gate_spec,
                    algorithmic_files=algorithmic_files,
                    architectural_files=architectural_files,
                    component_manifest_path=component_manifest_path,
                    component_manifest=component_manifest,
                    pin_coverage_report=pin_coverage_report,
                )
            except Exception as exc:
                result = self._gate_execution_exception(gate_id, gate_spec, exc)
            results.append(result)

        total_duration = (time.monotonic() - start) * 1000
        return self._build_report(results, total_duration)

    def run_single_check(self, gate_id: GateId) -> GateCheckResult:
        """Run a single gate check by ID."""
        gate_spec = self._config.get_gate(gate_id)
        self._snapshot_load_failures = []
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
        changed_files = [
            str(path).strip()
            for path in (self._bundle.diff.changed_files or [])
            if isinstance(path, str) and str(path).strip()
        ]

        graph_snapshot_failures = self._snapshot_failures_for("graph_snapshot")
        pins_snapshot_failures = self._snapshot_failures_for("pins_snapshot")
        if graph_snapshot_failures and gate_id in {
            GateId.PIN_COVERAGE,
            GateId.INTRODUCED_ALGORITHM_SPECS,
            GateId.NO_INLINED_ATOM_LOGIC,
            GateId.FUNCTION_RECOMPOSITION,
            GateId.CONFIG_EXTERNALIZATION,
        }:
            return (
                self._snapshot_failure_gate(gate_id, gate_spec, graph_snapshot_failures),
                pin_coverage_report,
            )
        if pins_snapshot_failures and gate_id == GateId.NO_INLINED_ATOM_LOGIC:
            return (
                self._snapshot_failure_gate(gate_id, gate_spec, pins_snapshot_failures),
                pin_coverage_report,
            )

        if gate_id == GateId.NO_REMAINING_COMMENTS:
            return (
                check_no_remaining_comments(self._bundle, gate_spec),
                pin_coverage_report,
            )

        if gate_id == GateId.NO_STUB_FUNCTIONS:
            return (
                check_no_stub_functions(self._bundle, gate_spec),
                pin_coverage_report,
            )

        if gate_id == GateId.ALL_TESTS_PASS:
            return (
                check_all_tests_pass(self._config.test_command, self._project_root, gate_spec),
                pin_coverage_report,
            )

        if gate_id == GateId.CALL_GRAPH_CONNECTED:
            return (
                check_call_graph_connected(self._bundle, gate_spec),
                pin_coverage_report,
            )

        if gate_id == GateId.STORE_MONOGAMY:
            return (
                check_store_monogamy(self._bundle, gate_spec),
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
                changed_files=changed_files,
                analyzed=self._architectural_analyzed,
            )
            pin_coverage_report = build_pin_coverage_report(
                self._pin_registry,
                architectural_files,
                changed_files=changed_files,
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
                    changed_files=changed_files,
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
        """Resolve algorithmic files strictly from EvidenceBundle artifacts."""
        files = self._collect_files_from_pins_snapshot()
        files.extend(self._collect_algorithmic_files_from_facts())
        return self._dedupe_paths(files)

    def _resolve_architectural_files(self) -> list[Path]:
        """Resolve architectural files strictly from EvidenceBundle artifacts."""
        return self._dedupe_paths(self._collect_files_from_graph_snapshot())

    def _collect_files_from_pins_snapshot(self) -> list[Path]:
        """Collect algorithmic file paths from a pins snapshot payload."""
        payload = self._load_snapshot_payload(self._bundle.pins_snapshot.path, "pins_snapshot")
        pins = payload.get("pins")
        if not isinstance(pins, list):
            return []

        files: list[Path] = []
        for pin in pins:
            if not isinstance(pin, dict):
                continue
            candidate = pin.get("file_path") or pin.get("file")
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            files.append(self._as_project_path(candidate))
        return files

    def _collect_files_from_graph_snapshot(self) -> list[Path]:
        """Collect architectural file paths from a graph snapshot payload."""
        payload = self._load_snapshot_payload(self._bundle.graph_snapshot.path, "graph_snapshot")
        edges = payload.get("edges")
        if not isinstance(edges, list):
            return []

        files: list[Path] = []
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
            files.append(self._as_project_path(candidate))
        return files

    def _collect_algorithmic_files_from_facts(self) -> list[Path]:
        files: list[Path] = []
        for fn in (self._bundle.facts.functions or {}).values():
            if not isinstance(fn, dict):
                continue
            file_path = fn.get("file")
            if isinstance(file_path, str) and file_path.strip():
                files.append(self._as_project_path(file_path))
        for atom in (self._bundle.facts.atoms or {}).values():
            if not isinstance(atom, dict):
                continue
            file_path = atom.get("file")
            if isinstance(file_path, str) and file_path.strip():
                files.append(self._as_project_path(file_path))
        return files

    def _load_snapshot_payload(self, relative_path: str, artifact: str) -> dict[str, Any]:
        if not isinstance(relative_path, str) or not relative_path.strip():
            self._record_snapshot_failure(
                artifact=artifact,
                relative_path=str(relative_path),
                reason="missing_snapshot_path",
            )
            return {}
        snapshot_path = self._evidence_iteration_dir() / relative_path
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except OSError as exc:
            self._record_snapshot_failure(
                artifact=artifact,
                relative_path=relative_path,
                reason=f"snapshot_read_error:{type(exc).__name__}",
            )
            return {}
        except json.JSONDecodeError:
            self._record_snapshot_failure(
                artifact=artifact,
                relative_path=relative_path,
                reason="snapshot_decode_error:JSONDecodeError",
            )
            return {}
        if not isinstance(payload, dict):
            self._record_snapshot_failure(
                artifact=artifact,
                relative_path=relative_path,
                reason=f"snapshot_invalid_payload_type:{type(payload).__name__}",
            )
            return {}
        return payload

    def _record_snapshot_failure(self, *, artifact: str, relative_path: str, reason: str) -> None:
        record = {
            "artifact": artifact,
            "path": relative_path,
            "reason": reason,
        }
        if record not in self._snapshot_load_failures:
            self._snapshot_load_failures.append(record)

    def _snapshot_failures_for(self, artifact: str) -> list[dict[str, Any]]:
        return [
            failure
            for failure in self._snapshot_load_failures
            if str(failure.get("artifact", "")).strip() == artifact
        ]

    def _evidence_iteration_dir(self) -> Path:
        evidence_root = Path(
            self._bundle.slice_root or self._bundle.workspace_root or self._project_root
        )
        return self._bundle.iter_dir(evidence_root)

    def _as_project_path(self, candidate: str) -> Path:
        path = Path(candidate)
        if path.is_absolute():
            return path.resolve()
        return (self._project_root / path).resolve()

    @staticmethod
    def _dedupe_paths(paths: list[Path]) -> list[Path]:
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = path.as_posix()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)
        return deduped

    def _atom_registry_for_coverage(self) -> AtomRegistry:
        from spec_manager.branches.atoms import AtomRegistry as _AtomRegistry
        from spec_manager.branches.layout import BranchLayout

        layout = BranchLayout(run_root=self._project_root)
        return _AtomRegistry(layout)

    def _load_provenance(self) -> ProvenanceRegistry:
        if self._provenance_registry_path:
            return ProvenanceRegistry.load(self._provenance_registry_path)
        return ProvenanceRegistry()

    def _load_component_manifest(self) -> tuple[Path | None, dict[str, Any] | None]:
        """Load component manifest from explicit path, current iteration, or project root."""
        path = self._component_manifest_path_override
        if path is None:
            iteration_manifest = self._evidence_iteration_dir() / "component_manifest.json"
            if iteration_manifest.exists():
                path = iteration_manifest
            else:
                direct = self._project_root / "component_manifest.json"
                if direct.exists():
                    path = direct

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
            mode=gate_spec.mode.value,
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
            mode=gate_spec.mode.value,
            status=GateStatus.AMBIGUOUS,
            score=0.0,
            findings=[{"reason": "gate_not_implemented", "configured_mode": gate_spec.mode.value}],
            summary=f"Gate '{gate_id.value}' is not implemented",
            duration_ms=0.0,
        )

    @staticmethod
    def _gate_execution_exception(
        gate_id: GateId,
        gate_spec: GateSpec,
        exc: Exception,
    ) -> GateCheckResult:
        return GateCheckResult(
            gate_id=gate_id.value,
            mode=gate_spec.mode.value,
            status=GateStatus.AMBIGUOUS,
            score=0.0,
            findings=[
                {
                    "reason": "gate_execution_exception",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            ],
            summary=(
                f"Gate '{gate_id.value}' raised {type(exc).__name__}; "
                "continuing with remaining gates"
            ),
            duration_ms=0.0,
        )

    @staticmethod
    def _snapshot_failure_gate(
        gate_id: GateId,
        gate_spec: GateSpec,
        snapshot_failures: list[dict[str, Any]],
    ) -> GateCheckResult:
        findings = [dict(item) for item in snapshot_failures]
        findings.append({"configured_mode": gate_spec.mode.value})
        return GateCheckResult(
            gate_id=gate_id.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=findings,
            summary="Gate blocked by snapshot evidence load failure",
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
