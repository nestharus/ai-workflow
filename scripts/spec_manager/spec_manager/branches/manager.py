"""Unified facade for the branch organization system.

Integrates all branch subsystems behind a single entry point:
- BranchLayout (directory structure)
- AtomRegistry (shared atoms)
- PinRegistry (atom-to-architecture mapping)
- SliceNavigator (vertical/horizontal navigation)
- PromotionEngine (upward flow)
- DownwardFlowEngine (downward flow)
- CollapseEngine (codebase ingestion)
- AnalysisGenerator (computed analysis)
"""

from __future__ import annotations

from pathlib import Path

from .analysis import AnalysisGenerator, AnalysisReport
from .atoms import AtomRegistry
from .collapse import CollapseEngine, CollapseResult
from .downward_flow import ArchitecturalIssue, DownwardFlowEngine, DownwardTraceResult
from .layout import BranchLayout
from .pins import PinRegistry
from .promotion import PromotionEngine, PromotionResult
from .slices import SliceNavigator
from .types import (
    AtomDescriptor,
    AtomKind,
    PinProjection,
    VerticalSlice,
)


class BranchManager:
    """Unified facade for the branch organization system.

    Integrates:
    - BranchLayout (directory structure)
    - AtomRegistry (shared atoms)
    - PinRegistry (atom-to-architecture mapping)
    - SliceNavigator (vertical/horizontal navigation)
    - PromotionEngine (upward flow)
    - DownwardFlowEngine (downward flow)
    - CollapseEngine (codebase ingestion)
    - AnalysisGenerator (computed analysis)
    """

    def __init__(self, run_root: Path) -> None:
        self._layout = BranchLayout(run_root)
        self._atom_registry = AtomRegistry.load(self._layout)
        self._pin_registry = PinRegistry.load(self._layout)
        self._slice_navigator = SliceNavigator(
            self._layout, self._atom_registry, self._pin_registry
        )
        self._promotion_engine = PromotionEngine(
            self._layout, self._atom_registry, self._pin_registry
        )
        self._downward_flow = DownwardFlowEngine(
            self._layout, self._atom_registry, self._pin_registry
        )
        self._collapse_engine = CollapseEngine(self._layout)
        self._analysis_generator = AnalysisGenerator(
            self._layout, self._atom_registry, self._pin_registry, self._slice_navigator
        )

    # ---- Properties ----

    @property
    def layout(self) -> BranchLayout:
        """Access the branch layout."""
        return self._layout

    @property
    def atom_registry(self) -> AtomRegistry:
        """Access the atom registry."""
        return self._atom_registry

    @property
    def pin_registry(self) -> PinRegistry:
        """Access the pin registry."""
        return self._pin_registry

    @property
    def slice_navigator(self) -> SliceNavigator:
        """Access the slice navigator."""
        return self._slice_navigator

    # ---- Lifecycle ----

    def initialize(self, force: bool = False) -> list[str]:
        """Initialize the branch directory structure.

        Args:
            force: If ``True``, recreate even if already initialized.

        Returns:
            List of issues encountered (empty if successful).
        """
        if self.is_initialized() and not force:
            return []
        self._layout.initialize()
        return self._layout.validate()

    def is_initialized(self) -> bool:
        """Check if the branch system has been initialized."""
        return self._layout.branches_dir.exists() and self._layout.atoms_dir.exists()

    # ---- Atom management ----

    def register_atom(self, descriptor: AtomDescriptor) -> None:
        """Register an atom in the shared registry.

        Args:
            descriptor: The atom descriptor to register.
        """
        self._atom_registry.register(descriptor)

    def get_atom(self, atom_id: str) -> AtomDescriptor | None:
        """Look up an atom by ID.

        Args:
            atom_id: The atom ID to look up.

        Returns:
            The descriptor, or ``None`` if not found.
        """
        return self._atom_registry.get(atom_id)

    def list_atoms(self, kind: AtomKind | None = None) -> list[AtomDescriptor]:
        """List all atoms, optionally filtered by kind.

        Args:
            kind: If provided, filter to this kind only.

        Returns:
            List of atom descriptors.
        """
        if kind is not None:
            return self._atom_registry.list_by_kind(kind)
        return self._atom_registry.list_all()

    # ---- Pin management ----

    def register_pin(self, pin: PinProjection) -> None:
        """Register a pin-function.

        Args:
            pin: The pin to register.
        """
        self._pin_registry.register_pin(pin)

    def trace_forward(self, atom_id: str) -> list[PinProjection]:
        """Forward trace: atom -> all architectural locations.

        Args:
            atom_id: The atom ID to trace.

        Returns:
            List of PinProjection records.
        """
        return self._pin_registry.get_architectural_locations(atom_id)

    def trace_backward(self, location: str) -> PinProjection | None:
        """Backward trace: architectural location -> atom.

        Args:
            location: The architectural location string.

        Returns:
            The PinProjection at this location, or ``None``.
        """
        return self._pin_registry.get_atom_for_location(location)

    # ---- Promotion ----

    def promote(
        self,
        atom_ids: list[str] | None = None,
        skip_compliance: bool = False,
    ) -> PromotionResult:
        """Promote atoms from algorithmic to architectural branch.

        Args:
            atom_ids: Specific atoms to promote (``None`` = all changed).
            skip_compliance: Skip compliance gate.

        Returns:
            PromotionResult describing the outcome.
        """
        slices = list(self._slice_navigator._slices.values())
        return self._promotion_engine.promote(
            atom_ids=atom_ids,
            skip_compliance=skip_compliance,
            slices=slices if slices else None,
        )

    # ---- Downward flow ----

    def trace_issue(self, issue: ArchitecturalIssue) -> DownwardTraceResult:
        """Trace an architectural issue back to its atom origin.

        Args:
            issue: The architectural issue to trace.

        Returns:
            DownwardTraceResult with traced pins and atoms.
        """
        return self._downward_flow.trace_issue(issue)

    # ---- Collapse ----

    def collapse_codebase(self, source_dir: Path) -> CollapseResult:
        """Route an existing codebase to initial brownfield artifacts.

        Args:
            source_dir: Root directory of the source codebase.

        Returns:
            CollapseResult with routing decisions.
        """
        return self._collapse_engine.collapse(source_dir)

    # ---- Analysis ----

    def regenerate_analysis(self) -> AnalysisReport:
        """Regenerate the analysis branch from current state.

        Returns:
            AnalysisReport with full analysis.
        """
        report = self._analysis_generator.generate()
        self._analysis_generator.write_lineage_table(report)
        self._analysis_generator.write_adjacency_graph(report)
        self._analysis_generator.write_drift_report(report)
        return report

    # ---- Navigation ----

    def navigate_down(self, atom_id: str) -> AtomDescriptor:
        """From any layer, navigate down to the algorithmic atom.

        Args:
            atom_id: The atom to navigate to.

        Returns:
            The AtomDescriptor.

        Raises:
            KeyError: If the atom is not found.
        """
        return self._slice_navigator.navigate_down(atom_id)

    def navigate_up(self, atom_id: str) -> list[PinProjection]:
        """From an atom, navigate up to all architectural locations.

        Args:
            atom_id: The atom to trace upward.

        Returns:
            List of PinProjection records.
        """
        return self._slice_navigator.navigate_up(atom_id)

    def navigate_across(self, slice_id: str) -> list[VerticalSlice]:
        """From a vertical slice, see sibling components.

        Args:
            slice_id: The slice to find siblings for.

        Returns:
            List of sibling VerticalSlice objects.
        """
        return self._slice_navigator.navigate_across(slice_id)

    # ---- Slice management ----

    def create_slice(self, name: str, parent: str | None = None) -> VerticalSlice:
        """Create a new vertical slice.

        Args:
            name: Human-readable name for the slice.
            parent: Parent slice ID, or ``None`` for root.

        Returns:
            The created VerticalSlice.
        """
        return self._slice_navigator.create_slice(name, parent)

    def validate_store_monogamy(self) -> list[str]:
        """Validate that each store is in exactly one vertical slice.

        Returns:
            List of violation descriptions. Empty if valid.
        """
        return self._slice_navigator.validate_store_monogamy()

    # ---- Persistence ----

    def save(self) -> None:
        """Save all registries and state to disk."""
        self._atom_registry.save()
        self._pin_registry.save()
        self._slice_navigator.save()

    def load(self) -> None:
        """Load all registries and state from disk."""
        self._atom_registry = AtomRegistry.load(self._layout)
        self._pin_registry = PinRegistry.load(self._layout)
        self._slice_navigator = SliceNavigator.load(
            self._layout, self._atom_registry, self._pin_registry
        )
        # Re-wire engines with loaded registries
        self._promotion_engine = PromotionEngine(
            self._layout, self._atom_registry, self._pin_registry
        )
        self._downward_flow = DownwardFlowEngine(
            self._layout, self._atom_registry, self._pin_registry
        )
        self._analysis_generator = AnalysisGenerator(
            self._layout, self._atom_registry, self._pin_registry, self._slice_navigator
        )
