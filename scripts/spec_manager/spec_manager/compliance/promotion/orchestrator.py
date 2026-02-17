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
# IMPL(single-layer): `INTRODUCED_ALGORITHM_SPECS` should be scheduled for both
# Libraries and Architecture groups once `introduction_checker` consumes deterministic
# diff + shape/verifier inputs; remove PinFunctionRegistry gating for this check in the
# same migration change.
# IMPL(single-layer): `PROVENANCE_COMPLETE` should consume work-item provenance
# requirements from routing/work-item queues (`required_work_items`) instead of
# PinFunctionRegistry-wide scans, and only deterministic evidence fields can satisfy it.
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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from spec_manager.compliance.promotion.algorithmic_gates import (
    check_all_tests_pass,
    check_call_graph_connected,
    check_no_remaining_comments,
    check_no_stub_functions,
    check_store_monogamy,
)
from spec_manager.compliance.promotion.architectural_quality import (
    ArchitectureGateContext,
    check_config_externalization,
    check_event_handler_coverage,
    check_function_recomposition,
    check_import_boundary_per_shape,
    check_no_orphan_components,
    check_shape_drift_resolved,
)
from spec_manager.compliance.promotion.config import (
    GATE_PHASES,
    GateId,
    GateMode,
    GateSpec,
    PhaseId,
    PromotionGateConfig,
)
from spec_manager.compliance.promotion.introduction_checker import (
    check_introduced_algorithm_specs,
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
from spec_manager.orchestration.evidence import EvidenceBundle
from spec_manager.routing import (
    ShapeId,
    ShapeMatchReport,
    ShapePackIndex,
    VerifierRunSummary,
    enforce_non_ship_policy,
    generate_work_items_from_reports,
    load_shape_pack,
    match_all_shapes,
    run_all_active_shape_verifiers,
)
from spec_manager.routing.matcher import MatchPolicy, build_observed_dependency_graph
from spec_manager.schemas.pin_functions import PinFunctionRegistry

if TYPE_CHECKING:
    from spec_manager.branches.atoms import AtomRegistry
    from spec_manager.core.evidence_index import EvidenceIndex
    from spec_manager.schemas.entities import EntitiesArtifact


AspectGateGroup = Literal["behavior", "architecture", "quality"]
PHASE_ORDER: tuple[PhaseId, ...] = ("libraries", "architecture", "quality")
GROUP_GATES: dict[AspectGateGroup, tuple[GateId, ...]] = {
    "behavior": (
        GateId.NO_REMAINING_COMMENTS,
        GateId.NO_STUB_FUNCTIONS,
        GateId.ALL_TESTS_PASS,
        GateId.CALL_GRAPH_CONNECTED,
        GateId.STORE_MONOGAMY,
        GateId.INTRODUCED_ALGORITHM_SPECS,
    ),
    "architecture": (
        GateId.FUNCTION_RECOMPOSITION,
        GateId.NO_ORPHAN_COMPONENTS,
        GateId.EVENT_HANDLER_COVERAGE,
        GateId.CONFIG_EXTERNALIZATION,
        GateId.SHAPE_VERIFIERS_PASS,
        GateId.IMPORT_BOUNDARY_CHECK,
        GateId.SHAPE_DRIFT_RESOLVED,
    ),
    "quality": (
        GateId.NO_REMAINING_COMMENTS,
        GateId.PROVENANCE_COMPLETE,
        GateId.ENTITY_COVERAGE,
    ),
}
GATE_GROUP_MAP: dict[GateId, AspectGateGroup] = {
    gate_id: group for group, gate_ids in GROUP_GATES.items() for gate_id in gate_ids
}


@dataclass
class GateRunContext:
    active_phase: PhaseId
    component_manifest_path: Path | None
    component_manifest: dict[str, Any] | None
    algorithmic_files: list[Path]
    architectural_files: list[Path]
    changed_files: list[Path]
    shape_index: ShapePackIndex | None
    shape_reports: dict[ShapeId, ShapeMatchReport]
    verifier_summaries: dict[ShapeId, VerifierRunSummary]
    required_contract_shape_ids: set[str]
    required_work_items: list[str]
    snapshot_failures: list[dict[str, Any]]


class LayerPromotionGate:
    """Orchestrates all promotion gate checks."""
    # IMPL(single-layer): Transitional class name only. Replace with
    # `AspectPromotionGate` once phase/aspect group dispatch is implemented end-to-end.

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

        results_by_gate: dict[str, GateCheckResult] = {}
        ordered_gate_ids: list[str] = []
        last_ctx: GateRunContext | None = None

        for phase in PHASE_ORDER:
            ctx = self._build_gate_context(
                active_phase=phase,
                algorithmic_files=algorithmic_files,
                architectural_files=architectural_files,
                component_manifest_path=component_manifest_path,
                component_manifest=component_manifest,
            )
            last_ctx = ctx

            for group in ("behavior", "architecture", "quality"):
                for result in self.run_group(group=group, ctx=ctx):
                    if result.gate_id not in results_by_gate:
                        ordered_gate_ids.append(result.gate_id)
                    results_by_gate[result.gate_id] = result

        if last_ctx is not None:
            non_ship_result = self.evaluate_non_ship(last_ctx)
            if non_ship_result.gate_id not in results_by_gate:
                ordered_gate_ids.append(non_ship_result.gate_id)
            results_by_gate[non_ship_result.gate_id] = non_ship_result

        total_duration = (time.monotonic() - start) * 1000
        ordered_results = [results_by_gate[gate_id] for gate_id in ordered_gate_ids]
        return self._build_report(ordered_results, total_duration)

    def run_single_check(self, gate_id: GateId) -> GateCheckResult:
        """Run a single gate check by ID."""
        gate_spec = self._config.get_gate(gate_id)
        self._snapshot_load_failures = []
        algorithmic_files = self._resolve_algorithmic_files()
        architectural_files = self._resolve_architectural_files()
        component_manifest_path, component_manifest = self._load_component_manifest()

        allowed_phases = GATE_PHASES.get(gate_id, ())
        if not allowed_phases:
            return self._not_implemented_gate(gate_id, gate_spec)

        ctx = self._build_gate_context(
            active_phase=allowed_phases[0],
            algorithmic_files=algorithmic_files,
            architectural_files=architectural_files,
            component_manifest_path=component_manifest_path,
            component_manifest=component_manifest,
        )
        group = GATE_GROUP_MAP.get(gate_id)
        if group is None:
            return self._not_implemented_gate(gate_id, gate_spec)

        result_candidates = self.run_group(group=group, ctx=ctx, selected_gate_ids=(gate_id,))
        for result in result_candidates:
            if result.gate_id == gate_id.value:
                return result

        return self._not_implemented_gate(gate_id, gate_spec)

    def run_group(
        self,
        *,
        group: AspectGateGroup,
        ctx: GateRunContext,
        selected_gate_ids: tuple[GateId, ...] | None = None,
    ) -> list[GateCheckResult]:
        """Execute all eligible gates for an aspect group in one phase."""
        group_gates = selected_gate_ids or GROUP_GATES[group]
        results: list[GateCheckResult] = []

        for gate_id in group_gates:
            gate_spec = self._config.get_gate(gate_id)
            if not gate_spec.enabled and selected_gate_ids is None:
                continue
            if ctx.active_phase not in GATE_PHASES[gate_id]:
                continue

            try:
                result = self._execute_gate(gate_id=gate_id, gate_spec=gate_spec, ctx=ctx)
            except Exception as exc:
                result = self._gate_execution_exception(gate_id, gate_spec, exc)
            results.append(result)

        return results

    def evaluate_non_ship(self, ctx: GateRunContext) -> GateCheckResult:
        """Emit deterministic non-ship hard-stop based on verifier-backed contract coverage."""
        required_contract_shape_ids = {ShapeId(shape_id) for shape_id in ctx.required_contract_shape_ids}
        non_ship_block, blockers = enforce_non_ship_policy(ctx.verifier_summaries, required_contract_shape_ids)

        if non_ship_block:
            return GateCheckResult(
                gate_id="non_ship_policy",
                mode=GateMode.REQUIRED.value,
                status=GateStatus.FAILED,
                score=0.0,
                findings=[
                    {
                        "reason": "non_ship_policy",
                        "detail": blocker,
                    }
                    for blocker in blockers
                ],
                summary="Non-ship policy blocked promotion for contract-backed verifier gaps",
                duration_ms=0.0,
            )

        return GateCheckResult(
            gate_id="non_ship_policy",
            mode=GateMode.REQUIRED.value,
            status=GateStatus.PASSED,
            score=1.0,
            findings=[],
            summary="Non-ship policy requirements are satisfied",
            duration_ms=0.0,
        )

    def _build_gate_context(
        self,
        *,
        active_phase: PhaseId,
        algorithmic_files: list[Path],
        architectural_files: list[Path],
        component_manifest_path: Path | None,
        component_manifest: dict[str, Any] | None,
    ) -> GateRunContext:
        changed_files = [
            self._as_project_path(path)
            for path in (self._bundle.diff.changed_files or [])
            if isinstance(path, str) and str(path).strip()
        ]

        shape_index: ShapePackIndex | None = None
        shape_reports: dict[ShapeId, ShapeMatchReport] = {}
        verifier_summaries: dict[ShapeId, VerifierRunSummary] = {}
        required_contract_shape_ids: set[str] = set()
        required_work_items: list[str] = []

        try:
            shape_index = load_shape_pack(self._project_root)
        except Exception as exc:
            self._record_snapshot_failure(
                artifact="shape_pack",
                relative_path="routing/index.json",
                reason=f"shape_pack_load_error:{type(exc).__name__}",
            )

        if shape_index is not None:
            required_contract_shape_ids = {
                str(shape.shape_id)
                for shape in shape_index.shapes.values()
                if str(shape.status).upper() == "ACTIVE" and bool(shape.contracts)
            }

            try:
                verifier_summaries = run_all_active_shape_verifiers(
                    index=shape_index,
                    workspace_root=self._project_root,
                )
            except Exception as exc:
                self._record_snapshot_failure(
                    artifact="shape_verifiers",
                    relative_path=str(self._project_root),
                    reason=f"shape_verifiers_error:{type(exc).__name__}",
                )
                verifier_summaries = {}

            verifier_results_by_shape = {
                shape_id: summary.results for shape_id, summary in verifier_summaries.items()
            }

            try:
                observed_graph = build_observed_dependency_graph(self._project_root)
            except Exception as exc:
                self._record_snapshot_failure(
                    artifact="observed_dependency_graph",
                    relative_path=str(self._project_root),
                    reason=f"dependency_graph_error:{type(exc).__name__}",
                )
                observed_graph = {}
            else:
                try:
                    shape_reports = match_all_shapes(
                        shape_index,
                        observed_graph,
                        verifier_results_by_shape,
                        MatchPolicy(),
                    )
                except Exception as exc:
                    self._record_snapshot_failure(
                        artifact="shape_matcher",
                        relative_path=str(self._project_root),
                        reason=f"shape_match_error:{type(exc).__name__}",
                    )

        if shape_reports:
            required_work_items = [
                item.work_item_id
                for item in generate_work_items_from_reports(
                    shape_reports,
                    phase=active_phase,
                    cycle=1,
                )
            ]

        return GateRunContext(
            active_phase=active_phase,
            component_manifest_path=component_manifest_path,
            component_manifest=component_manifest,
            algorithmic_files=algorithmic_files,
            architectural_files=architectural_files,
            changed_files=changed_files,
            shape_index=shape_index,
            shape_reports=shape_reports,
            verifier_summaries=verifier_summaries,
            required_contract_shape_ids=required_contract_shape_ids,
            required_work_items=required_work_items,
            snapshot_failures=list(self._snapshot_load_failures),
        )

    def _execute_gate(
        self,
        *,
        gate_id: GateId,
        gate_spec: GateSpec,
        ctx: GateRunContext,
    ) -> GateCheckResult:
        """Dispatch one gate execution."""
        if gate_id == GateId.NO_REMAINING_COMMENTS:
            return check_no_remaining_comments(self._bundle, gate_spec)

        if gate_id == GateId.NO_STUB_FUNCTIONS:
            return check_no_stub_functions(self._bundle, gate_spec)

        if gate_id == GateId.ALL_TESTS_PASS:
            return check_all_tests_pass(
                self._config.test_command,
                self._project_root,
                gate_spec,
            )

        if gate_id == GateId.CALL_GRAPH_CONNECTED:
            return check_call_graph_connected(self._bundle, gate_spec)

        if gate_id == GateId.STORE_MONOGAMY:
            return check_store_monogamy(self._bundle, gate_spec)

        if gate_id == GateId.INTRODUCED_ALGORITHM_SPECS:
            if ctx.shape_index is None:
                return self._missing_evidence_gate(
                    gate_id,
                    gate_spec,
                    "Shape pack not available",
                )
            if not ctx.verifier_summaries:
                return self._missing_evidence_gate(
                    gate_id,
                    gate_spec,
                    "No shape verifier summaries available",
                )
            return check_introduced_algorithm_specs(
                changed_files=ctx.changed_files,
                shape_index=ctx.shape_index,
                verifier_summary=ctx.verifier_summaries,
                gate_spec=gate_spec,
                workspace=self._project_root,
                active_phase=ctx.active_phase,
            )

        if gate_id == GateId.FUNCTION_RECOMPOSITION:
            if self._pin_registry is None:
                return self._missing_evidence_gate(
                    gate_id,
                    gate_spec,
                    "PinFunctionRegistry not provided",
                )
            return check_function_recomposition(
                self._pin_registry,
                ctx.architectural_files,
                gate_spec,
                analyzed_arch=self._architectural_analyzed,
            )

        if gate_id == GateId.NO_ORPHAN_COMPONENTS:
            if ctx.component_manifest is None:
                return self._missing_evidence_gate(
                    gate_id,
                    gate_spec,
                    "Component manifest not provided",
                )
            return check_no_orphan_components(ctx.component_manifest, gate_spec)

        if gate_id == GateId.EVENT_HANDLER_COVERAGE:
            if ctx.component_manifest is None:
                return self._missing_evidence_gate(
                    gate_id,
                    gate_spec,
                    "Component manifest not provided",
                )
            return check_event_handler_coverage(ctx.component_manifest, gate_spec)

        if gate_id == GateId.CONFIG_EXTERNALIZATION:
            return check_config_externalization(
                ctx.architectural_files,
                gate_spec,
                analyzed_arch=self._architectural_analyzed,
            )

        if gate_id == GateId.SHAPE_VERIFIERS_PASS:
            if ctx.shape_index is None:
                return self._missing_evidence_gate(
                    gate_id,
                    gate_spec,
                    "Shape pack not available",
                )
            if ctx.shape_index.shapes and not ctx.verifier_summaries:
                return self._missing_evidence_gate(
                    gate_id,
                    gate_spec,
                    "No shape verifier summaries available",
                )
            active_shape_ids = {
                shape_id
                for shape_id, shape in ctx.shape_index.shapes.items()
                if str(getattr(shape, "status", "")).upper() == "ACTIVE"
            }
            missing_shape_summaries = active_shape_ids - set(ctx.verifier_summaries)
            if missing_shape_summaries:
                return self._missing_evidence_gate(
                    gate_id,
                    gate_spec,
                    (
                        "Missing shape verifier summaries for active shapes: "
                        + ", ".join(sorted(str(shape_id) for shape_id in missing_shape_summaries))
                    ),
                )

            findings: list[dict[str, Any]] = []
            for raw_shape_id, summary in sorted(
                ctx.verifier_summaries.items(),
                key=lambda item: str(item[0]),
            ):
                if raw_shape_id not in active_shape_ids:
                    continue
                passed = bool(summary.all_passed)
                if summary.missing_required or summary.non_ship_block or not passed:
                    findings.append(
                        {
                            "shape_id": str(raw_shape_id),
                            "all_passed": passed,
                            "non_ship_block": summary.non_ship_block,
                            "missing_required": list(summary.missing_required),
                            "results_total": len(summary.results),
                        }
                    )

            if findings:
                return GateCheckResult(
                    gate_id=gate_id.value,
                    mode=gate_spec.mode.value,
                    status=GateStatus.FAILED,
                    score=0.0,
                    findings=findings,
                    summary="Shape verifier suite is incomplete or failing",
                    duration_ms=0.0,
                )

            return GateCheckResult(
                gate_id=gate_id.value,
                mode=gate_spec.mode.value,
                status=GateStatus.PASSED,
                score=1.0,
                findings=[],
                summary="All shape verifier summaries passed",
                duration_ms=0.0,
            )

        if gate_id == GateId.IMPORT_BOUNDARY_CHECK:
            if ctx.shape_index is None:
                return self._missing_evidence_gate(
                    gate_id,
                    gate_spec,
                    "Shape pack not available",
                )
            return check_import_boundary_per_shape(
                ArchitectureGateContext(
                    shape_reports=ctx.shape_reports,
                    component_manifest=ctx.component_manifest,
                    analyzed_files=None,
                ),
                gate_spec=gate_spec,
                phase=ctx.active_phase,
            )

        if gate_id == GateId.SHAPE_DRIFT_RESOLVED:
            if ctx.shape_index is None:
                return self._missing_evidence_gate(
                    gate_id,
                    gate_spec,
                    "Shape pack not available",
                )
            return check_shape_drift_resolved(
                ArchitectureGateContext(
                    shape_reports=ctx.shape_reports,
                    component_manifest=ctx.component_manifest,
                    analyzed_files=None,
                ),
                gate_spec=gate_spec,
                phase=ctx.active_phase,
            )

        if gate_id == GateId.PROVENANCE_COMPLETE:
            return check_provenance_complete(
                self._load_provenance(),
                ctx.required_work_items,
                gate_spec,
            )

        if gate_id == GateId.ENTITY_COVERAGE:
            return self._run_entity_coverage(gate_spec)

        return self._not_implemented_gate(gate_id, gate_spec)

    def _run_entity_coverage_legacy(self, gate_spec: GateSpec) -> GateCheckResult:
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

    def _execute_gate_legacy(
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
        # IMPL(single-layer): Hard pass/fail must remain deterministic-only (Section 13.1).
        # LLM-derived diagnostics can inform routing/work items but never gate authority.
        changed_files = [
            str(path).strip()
            for path in (self._bundle.diff.changed_files or [])
            if isinstance(path, str) and str(path).strip()
        ]

        graph_snapshot_failures = self._snapshot_failures_for("graph_snapshot")
        pins_snapshot_failures = self._snapshot_failures_for("pins_snapshot")
        # IMPL(single-layer): Missing deterministic artifacts should emit
        # `STALE_EVIDENCE` for any hard deterministic gate in the active phase, not
        # only legacy pin-era gate IDs.
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
            # IMPL(single-layer): Section 10.2 eliminates PIN_COVERAGE. Remove this
            # branch with GateId cleanup; replacement authority is shape verifier +
            # matcher evidence.
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
            # IMPL(single-layer): Rewire this branch to pass deterministic diff metadata,
            # shape ownership, and verifier summaries into `introduction_checker`;
            # remove pin coverage construction as part of Section 10.2 pin-gate retirement.
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
            # IMPL(single-layer): Section 10.2 eliminates this atom/arch divide gate.
            # Delete with its pin-registry dependency; contract verifier failures
            # should route to quality/architecture work items instead.
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
            # IMPL(single-layer): Keep/adapt gate but migrate off pin-registry inputs;
            # recomposition authority should come from shape-owned dependency evidence.
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
            # IMPL(single-layer): Section 10.2 eliminates PIN_CONSUMPTION_COVERAGE.
            # Remove this branch and rely on shape contracts + verifier coverage.
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
            # IMPL(single-layer): Section 10.2 eliminates EDGE_REALIZATION as a hard
            # gate; shape contract verifiers become the deterministic substitute.
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
            # IMPL(single-layer): Replace manifest hash drift checks with
            # matcher-derived shape drift (`SHAPE_DRIFT_RESOLVED`) and remove this
            # legacy branch in the same GateId migration.
            return check_arch_drift_pass(component_manifest_path, gate_spec), pin_coverage_report

        if gate_id == GateId.PROVENANCE_COMPLETE:
            # IMPL(single-layer): Provenance coverage should read required work-item
            # receipts/refs, not PinFunctionRegistry-wide scans.
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
            # IMPL(single-layer): Pin-alignment gating is removed with PIN retirement;
            # keep only until GateId cleanup lands.
            return self._run_test_pin_alignment_legacy(gate_spec), pin_coverage_report

        return self._not_implemented_gate(gate_id, gate_spec), pin_coverage_report

    def _run_test_pin_alignment_legacy(self, gate_spec: GateSpec) -> GateCheckResult:
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
        # IMPL(single-layer): Transition away from pins snapshot as primary source;
        # prefer deterministic changed-files + shape ownership resolution inputs.
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
        # IMPL(single-layer): Component manifest remains transitional evidence for
        # legacy pin/component gates; shape pack + matcher reports are the target
        # structural authority.
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
        # IMPL(single-layer): Report aggregation must include non-ship hard-stop state
        # (`non_ship_block=True`) once `evaluate_non_ship` is wired; this signal is
        # terminal even when ordinary required gates otherwise pass.
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
