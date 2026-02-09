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

from .atoms import AtomRegistry
from .compliance import ComplianceGateResult
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


# ---- Adapter helpers ----


def _promotion_report_to_compliance_result(report: PromotionReport) -> ComplianceGateResult:
    """Convert a canonical PromotionReport to branches ComplianceGateResult."""
    gate_passed: dict[str, bool] = {}
    for gr in report.gate_results:
        gate_passed[gr.gate_id] = gr.passed

    return ComplianceGateResult(
        passed=report.passed,
        no_comments=gate_passed.get(GateId.NO_REMAINING_COMMENTS.value, True),
        no_stubs=gate_passed.get(GateId.NO_STUB_FUNCTIONS.value, True),
        tests_pass=gate_passed.get(GateId.ALL_TESTS_PASS.value, True),
        call_graph_connected=gate_passed.get(GateId.CALL_GRAPH_CONNECTED.value, True),
        store_monogamy=gate_passed.get(GateId.STORE_MONOGAMY.value, True),
        errors=[b.summary for b in report.blockers],
        warnings=[w.summary for w in report.warnings],
    )


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
    ) -> PromotionResult:
        """Promote atoms from algorithmic to architectural branch.

        Args:
            atom_ids: Specific atoms to promote (``None`` = all changed).
            skip_compliance: Skip compliance gate (for development only).
            slices: Vertical slices for store monogamy check.

        Returns:
            PromotionResult describing the outcome.
        """
        compliance_result: ComplianceGateResult | None = None

        if not skip_compliance:
            compliance_result = self._check_compliance(slices)
            if not compliance_result.passed:
                # TODO: Trigger demotion on compliance failure instead
                #   of just returning failure. DownwardFlowEngine should
                #   trace pins back to atoms, identify what needs fixing
                #   at L1 (code-as-spec), fix it, then retry promotion.
                #   Current behavior: returns skipped, caller ignores.
                return PromotionResult(
                    success=False,
                    promoted_atoms=[],
                    skipped_atoms=[],
                    compliance_result=compliance_result,
                    pin_ids_created=[],
                    errors=compliance_result.errors,
                )

        # Identify atoms to promote
        if atom_ids is None:
            atom_ids = self._identify_changed_atoms()

        promoted: list[str] = []
        skipped: list[str] = []
        new_pins: list[str] = []
        errors: list[str] = []

        for atom_id in atom_ids:
            descriptor = self._atom_registry.get(atom_id)
            if descriptor is None:
                errors.append(f"Atom not found: {atom_id}")
                continue

            # Check if already projected
            existing = self._pin_registry.get_architectural_locations(atom_id)
            if existing:
                skipped.append(atom_id)
                continue

            # Create a new pin for this atom
            pin = self._project_atom(atom_id)
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

        gate = LayerPromotionGate(config)
        report = gate.run_all_checks()
        result = _promotion_report_to_compliance_result(report)

        # Run branches-specific store monogamy if slices provided
        if slices is not None:
            store_owners: dict[str, list[str]] = {}
            for vs in slices:
                for store_id in vs.store_ids:
                    store_owners.setdefault(store_id, []).append(vs.slice_id)

            violations = {sid: owners for sid, owners in store_owners.items() if len(owners) > 1}
            if violations:
                result = ComplianceGateResult(
                    passed=False,
                    no_comments=result.no_comments,
                    no_stubs=result.no_stubs,
                    tests_pass=result.tests_pass,
                    call_graph_connected=result.call_graph_connected,
                    store_monogamy=False,
                    errors=result.errors
                    + [
                        f"Store {sid} owned by multiple slices: {', '.join(owners)}"
                        for sid, owners in violations.items()
                    ],
                    warnings=result.warnings,
                )

        return result

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

    def _project_atom(self, atom_id: str) -> PinProjection | None:
        """Create a pin for an atom using pass-through projection.

        By default, new atoms are projected as pass-through since the
        architecture imports them directly.

        Args:
            atom_id: The atom to project.

        Returns:
            A new PinProjection, or ``None`` if the atom is not found.
        """
        descriptor = self._atom_registry.get(atom_id)
        if descriptor is None:
            return None

        # TODO: Smart projection routing based on atom metadata.
        #   Currently always uses PASS_THROUGH. Should inspect the
        #   atom's role/context to select the appropriate ProjectionType:
        #   - EVENT_BRIDGE for event-emitting atoms
        #   - MIDDLEWARE_WRAP for cross-cutting concerns
        #   - RETRY_DECORATE for retry-capable operations
        #   - AGGREGATION for data-combining atoms
        #   Atom descriptor should carry enough metadata to decide.
        pin_id = self._pin_registry.allocate_pin_id()
        return PinProjection(
            pin_id=pin_id,
            atom_id=atom_id,
            architectural_location=f"services/{descriptor.function_name}",
            projection_type=ProjectionType.PASS_THROUGH,
            confidence=1.0,
        )
