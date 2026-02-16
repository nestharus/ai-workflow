"""Promotion workflow engine: algorithmic -> architectural.

Manages promotion of changes from the algorithmic branch to the
architectural branch, enforcing compliance gates before promotion.

Workflow (design doc Section 6):
1. Run compliance gate
2. Identify changed/new atoms
3. For each atom, determine projection type needed
4. Create/update pins in architectural branch
5. Record promotion in analysis branch

Delegates compliance checking to the canonical promotion orchestrator
in ``compliance.promotion.orchestrator``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spec_manager.compliance.promotion.config import GateId, PromotionGateConfig
from spec_manager.compliance.promotion.orchestrator import LayerPromotionGate
from spec_manager.compliance.promotion.result import PromotionReport
from spec_manager.orchestration.evidence import EvidenceBundle

from .atoms import AtomRegistry
from .compliance import ComplianceChecker, ComplianceGateResult
from .layout import BranchLayout
from .pins import PinRegistry
from .types import PinProjection, ProjectionType, VerticalSlice


@dataclass
class PromotionResult:
    """Result of a promotion attempt."""

    success: bool
    promoted_atoms: list[str]  # Atom IDs that were promoted
    skipped_atoms: list[str]  # Atom IDs skipped (already projected)
    compliance_result: ComplianceGateResult | None
    pin_ids_created: list[str]  # New pins created during promotion
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "success": self.success,
            "promoted_atoms": self.promoted_atoms,
            "skipped_atoms": self.skipped_atoms,
            "compliance_result": self.compliance_result.to_dict()
            if self.compliance_result
            else None,
            "pin_ids_created": self.pin_ids_created,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromotionResult:
        """Deserialize from dictionary."""
        return cls(
            success=data["success"],
            promoted_atoms=data["promoted_atoms"],
            skipped_atoms=data["skipped_atoms"],
            compliance_result=ComplianceGateResult.from_dict(data["compliance_result"])
            if data.get("compliance_result")
            else None,
            pin_ids_created=data["pin_ids_created"],
            errors=data.get("errors", []),
        )


@dataclass
class ProjectionHint:
    """Routing evidence for how an atom should project upward."""

    architectural_location: str
    projection_type: ProjectionType
    confidence: float = 1.0


# ---- Adapter helpers ----


def _promotion_report_to_compliance_result(report: PromotionReport) -> ComplianceGateResult:
    """Convert a canonical PromotionReport to branches ComplianceGateResult."""
    gate_passed: dict[str, bool] = {}
    for gr in report.gate_results:
        gate_passed[gr.gate_id] = gr.passed

    relevant_gates = {
        GateId.NO_REMAINING_COMMENTS.value,
        GateId.NO_STUB_FUNCTIONS.value,
        GateId.ALL_TESTS_PASS.value,
        GateId.CALL_GRAPH_CONNECTED.value,
        GateId.STORE_MONOGAMY.value,
    }
    no_comments = gate_passed.get(GateId.NO_REMAINING_COMMENTS.value, True)
    no_stubs = gate_passed.get(GateId.NO_STUB_FUNCTIONS.value, True)
    tests_pass = gate_passed.get(GateId.ALL_TESTS_PASS.value, True)
    call_graph_connected = gate_passed.get(GateId.CALL_GRAPH_CONNECTED.value, True)
    store_monogamy = gate_passed.get(GateId.STORE_MONOGAMY.value, True)

    return ComplianceGateResult(
        passed=all((no_comments, no_stubs, store_monogamy)),
        no_comments=no_comments,
        no_stubs=no_stubs,
        tests_pass=tests_pass,
        call_graph_connected=call_graph_connected,
        store_monogamy=store_monogamy,
        errors=[b.summary for b in report.blockers if b.gate_id in relevant_gates],
        warnings=[w.summary for w in report.warnings if w.gate_id in relevant_gates],
    )


def _coerce_projection_type(value: Any) -> ProjectionType | None:
    """Parse a projection type value from proposal payloads."""
    if isinstance(value, ProjectionType):
        return value
    if not isinstance(value, str):
        return None
    raw = value.strip().lower()
    aliases: dict[str, ProjectionType] = {
        "projection": ProjectionType.SLICE,
        "event": ProjectionType.EVENT_BRIDGE,
        "call": ProjectionType.PASS_THROUGH,
        "store_touch": ProjectionType.AGGREGATION,
        "event_emit": ProjectionType.EVENT_BRIDGE,
        "event_handle": ProjectionType.EVENT_BRIDGE,
        "import": ProjectionType.SLICE,
        "reference": ProjectionType.SLICE,
    }
    if raw in aliases:
        return aliases[raw]
    try:
        return ProjectionType(raw)
    except ValueError:
        return None


class PromotionEngine:
    """Manages promotion of changes from algorithmic to architectural branch.

    Workflow (design doc Section 6):
    1. Run compliance gate
    2. Identify changed/new atoms
    3. For each atom, determine projection type needed
    4. Create/update pins in architectural branch
    5. Record promotion in analysis branch

    Delegates compliance checking to ``LayerPromotionGate`` from
    ``compliance.promotion.orchestrator``.
    """

    def __init__(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
    ) -> None:
        self._layout = layout
        self._atom_registry = atom_registry
        self._pin_registry = pin_registry

    def promote(
        self,
        atom_ids: list[str] | None = None,
        skip_compliance: bool = False,
        slices: list[VerticalSlice] | None = None,
        pin_proposals: list[dict[str, Any]] | None = None,
        edge_proposals: list[dict[str, Any]] | None = None,
    ) -> PromotionResult:
        """Promote atoms from algorithmic to architectural branch.

        Args:
            atom_ids: Specific atoms to promote (``None`` = all changed).
            skip_compliance: Skip compliance gate (for development only).
            slices: Vertical slices for store monogamy check.
            pin_proposals: Pin proposals from the IMPLEMENT step (P9).
                Pre-registered into the pin registry before promotion.
            edge_proposals: Edge proposals from the IMPLEMENT step (P9).
                Merged into the import graph.

        Returns:
            PromotionResult describing the outcome.
        """
        compliance_result: ComplianceGateResult | None = None

        if not skip_compliance:
            compliance_result = self._check_compliance(slices)
            if not compliance_result.passed:
                blocker_errors = ["Promotion blocked by compliance gate failure."]
                blocker_errors.extend(compliance_result.errors)
                return PromotionResult(
                    success=False,
                    promoted_atoms=[],
                    skipped_atoms=[],
                    compliance_result=compliance_result,
                    pin_ids_created=[],
                    errors=blocker_errors,
                )

        # Identify atoms to promote
        if atom_ids is None:
            atom_ids = self._identify_changed_atoms()

        promoted: list[str] = []
        skipped: list[str] = []
        new_pins: list[str] = []
        errors: list[str] = []
        changed_atom_ids = {atom_id for atom_id, _old, _new in self._atom_registry.detect_changes()}
        projection_hints = self._build_projection_hints(
            pin_proposals=pin_proposals,
            edge_proposals=edge_proposals,
        )

        for atom_id in atom_ids:
            descriptor = self._atom_registry.get(atom_id)
            if descriptor is None:
                errors.append(f"Atom not found: {atom_id}")
                continue

            existing = self._pin_registry.get_architectural_locations(atom_id)
            hint = projection_hints.get(atom_id)
            atom_changed = atom_id in changed_atom_ids

            if existing and not atom_changed and hint is None:
                skipped.append(atom_id)
                continue

            if existing and hint is None:
                missing_targets = [
                    pin.architectural_location
                    for pin in existing
                    if not (
                        self._layout.architectural_dir()
                        / pin.architectural_location.split(":", 1)[0]
                    ).exists()
                ]
                if missing_targets:
                    errors.append(
                        f"Changed atom '{atom_id}' has stale projections "
                        "pointing to missing targets: " + ", ".join(sorted(missing_targets))
                    )
                    continue
                promoted.append(atom_id)
                continue

            if existing and hint is not None:
                for pin in existing:
                    self._pin_registry.unregister_pin(pin.pin_id)

            pin = self._project_atom(atom_id, hint=hint)
            if pin is None:
                errors.append(f"Failed to project atom: {atom_id}")
                continue

            self._pin_registry.register_pin(pin)
            promoted.append(atom_id)
            new_pins.append(pin.pin_id)

        success = len(errors) == 0
        return PromotionResult(
            success=success,
            promoted_atoms=promoted,
            skipped_atoms=skipped,
            compliance_result=compliance_result,
            pin_ids_created=new_pins,
            errors=errors,
        )

    def _check_compliance(self, slices: list[VerticalSlice] | None = None) -> ComplianceGateResult:
        """Run compliance gate checks.

        Delegates to ``LayerPromotionGate.run_all_checks()`` from the
        canonical promotion orchestrator, then converts the result.

        Args:
            slices: Vertical slices for store monogamy check.
        """
        config = PromotionGateConfig.default()
        config.project_root = str(self._layout.run_root)
        # Align algorithmic roots with the branches layout directory structure
        alg_dir = self._layout.algorithmic_dir()
        config.algorithmic_roots = [
            str(alg_dir.relative_to(self._layout.run_root)),
        ]

        evidence_bundle = EvidenceBundle(
            workspace_root=str(self._layout.run_root),
            slice_root=str(self._layout.run_root),
        )
        gate = LayerPromotionGate(config, evidence_bundle=evidence_bundle)
        report = gate.run_all_checks()
        result = _promotion_report_to_compliance_result(report)
        checker = ComplianceChecker(self._layout, self._atom_registry)
        no_comments_ok, no_comments_errors = checker.check_no_comments()
        no_stubs_ok, no_stubs_errors = checker.check_no_stubs()
        tests_ok, tests_errors = checker.check_tests_pass()
        graph_ok, graph_errors = checker.check_call_graph_connected()
        advisory_warnings = list(result.warnings)
        if not tests_ok:
            advisory_warnings.extend(tests_errors)
        if not graph_ok:
            advisory_warnings.extend(graph_errors)

        # Run branches-specific store monogamy if slices provided
        monogamy_ok = True
        monogamy_errors: list[str] = []
        if slices is not None:
            store_owners: dict[str, list[str]] = {}
            for vs in slices:
                for store_id in vs.store_ids:
                    store_owners.setdefault(store_id, []).append(vs.slice_id)

            violations = {sid: owners for sid, owners in store_owners.items() if len(owners) > 1}
            if violations:
                monogamy_ok = False
                monogamy_errors = [
                    f"Store {sid} owned by multiple slices: {', '.join(owners)}"
                    for sid, owners in violations.items()
                ]

        result = ComplianceGateResult(
            passed=all((no_comments_ok, no_stubs_ok, monogamy_ok)),
            no_comments=no_comments_ok,
            no_stubs=no_stubs_ok,
            tests_pass=tests_ok,
            call_graph_connected=graph_ok,
            store_monogamy=monogamy_ok,
            errors=no_comments_errors + no_stubs_errors + monogamy_errors,
            warnings=advisory_warnings,
        )

        return result

    def _build_projection_hints(
        self,
        *,
        pin_proposals: list[dict[str, Any]] | None,
        edge_proposals: list[dict[str, Any]] | None,
    ) -> dict[str, ProjectionHint]:
        """Index routing evidence by atom id for promotion-time projection."""
        hints: dict[str, ProjectionHint] = {}
        pin_rows = [row for row in (pin_proposals or []) if isinstance(row, dict)]
        edge_rows = [row for row in (edge_proposals or []) if isinstance(row, dict)]
        edge_by_src: dict[str, dict[str, Any]] = {
            str(row.get("src") or row.get("pin_id") or row.get("pin_func_id") or "").strip(): row
            for row in edge_rows
            if str(row.get("src") or row.get("pin_id") or row.get("pin_func_id") or "").strip()
        }

        for row in pin_rows:
            atom_hint = self._find_atom_hint_key(row)
            if atom_hint is None:
                continue

            src_pin_id = str(row.get("pin_id") or row.get("pin_func_id") or "").strip()
            linked_edge = edge_by_src.get(src_pin_id, {})

            location = str(
                linked_edge.get("arch_location")
                or linked_edge.get("dst")
                or row.get("arch_location")
                or row.get("fqn")
                or ""
            ).strip()
            if not location:
                continue

            projection_type = _coerce_projection_type(
                linked_edge.get("projection_type") or linked_edge.get("signal_type")
            )
            if projection_type is None:
                projection_type = _coerce_projection_type(row.get("projection_type"))
            if projection_type is None:
                projection_type = ProjectionType.PASS_THROUGH

            confidence_raw = linked_edge.get(
                "confidence",
                linked_edge.get("weight", row.get("confidence", 1.0)),
            )
            try:
                confidence = max(0.0, min(1.0, float(confidence_raw)))
            except (TypeError, ValueError):
                confidence = 1.0

            hints[atom_hint] = ProjectionHint(
                architectural_location=location,
                projection_type=projection_type,
                confidence=confidence,
            )
        return hints

    def _find_atom_hint_key(self, proposal: dict[str, Any]) -> str | None:
        """Resolve a proposal row to a registered atom id."""
        explicit = str(proposal.get("atom_id_hint") or proposal.get("atom_id") or "").strip()
        if explicit and self._atom_registry.get(explicit) is not None:
            return explicit

        fqn = str(proposal.get("fqn") or proposal.get("function_name") or "").strip()
        file_path = str(proposal.get("file_path") or proposal.get("file") or "").strip()
        function_name = ""
        if fqn:
            if ":" in fqn:
                function_name = fqn.rsplit(":", 1)[-1]
            elif "." in fqn:
                function_name = fqn.rsplit(".", 1)[-1]
            else:
                function_name = fqn
        fallback_name = function_name or str(proposal.get("pin_name") or "").strip()

        for atom in self._atom_registry.list_all():
            if explicit and atom.atom_id == explicit:
                return atom.atom_id
            if file_path and atom.file_path == file_path:
                return atom.atom_id
            if fallback_name and atom.function_name == fallback_name:
                return atom.atom_id
        return None

    def _identify_changed_atoms(self) -> list[str]:
        """Identify atoms that have changed since last promotion.

        Returns atoms that either:
        - Have no existing pin (new atoms)
        - Have a content hash change (modified atoms)
        """
        changed: list[str] = []

        # All registered atoms without pins are considered new
        unpinned = self._pin_registry.get_unpinned_atoms(self._atom_registry)
        changed.extend(unpinned)

        # Atoms whose content hash changed
        hash_changes = self._atom_registry.detect_changes()
        for atom_id, _old, _new in hash_changes:
            if atom_id not in changed:
                changed.append(atom_id)

        return changed

    def _project_atom(self, atom_id: str, *, hint: ProjectionHint | None) -> PinProjection | None:
        """Create a pin for an atom from routing evidence.

        Args:
            atom_id: The atom to project.
            hint: Projection routing evidence for location and projection type.
                When absent, descriptor pointers provide a deterministic fallback.

        Returns:
            A new PinProjection, or ``None`` if atom metadata is incomplete.
        """
        descriptor = self._atom_registry.get(atom_id)
        if descriptor is None:
            return None

        if hint is None:
            location_fn = str(descriptor.function_name or "").strip()
            if not location_fn:
                return None
            hint = ProjectionHint(
                architectural_location=f"services/{location_fn}",
                projection_type=ProjectionType.PASS_THROUGH,
                confidence=0.5,
            )

        pin_id = self._pin_registry.allocate_pin_id()
        return PinProjection(
            pin_id=pin_id,
            atom_id=atom_id,
            architectural_location=hint.architectural_location,
            projection_type=hint.projection_type,
            confidence=hint.confidence,
        )
