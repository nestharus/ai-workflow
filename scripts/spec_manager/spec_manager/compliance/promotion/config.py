# TODO(single-layer): RESTRUCTURE — GateId enum loses PIN_COVERAGE, PIN_CONSUMPTION_COVERAGE,
#   EDGE_REALIZATION, NO_INLINED_ATOM_LOGIC, ARCH_DRIFT_PASS (all pin/layer-dependent).
#   Gains: SHAPE_VERIFIERS_PASS, IMPORT_BOUNDARY_CHECK, SHAPE_DRIFT_RESOLVED.
#   Merge TESTS_PASS into ALL_TESTS_PASS — single unified hard gate (Section 10.2).
#   GateMode and GateSeverity KEEP. GateSpec KEEP but per-layer config eliminated.
#   Section 10.1 defines the three aspect gate groups.
# ALGORITHM(single-layer):
#   References: response3 Section 10.2.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] — three-phase forward-only pipeline.
#     - GateId enum must include: NO_REMAINING_COMMENTS, NO_STUB_FUNCTIONS, ALL_TESTS_PASS, CALL_GRAPH_CONNECTED, STORE_MONOGAMY, FUNCTION_RECOMPOSITION, NO_ORPHAN_COMPONENTS, EVENT_HANDLER_COVERAGE, CONFIG_EXTERNALIZATION, SHAPE_VERIFIERS_PASS, IMPORT_BOUNDARY_CHECK, SHAPE_DRIFT_RESOLVED, PROVENANCE_COMPLETE, ENTITY_COVERAGE.
#     - Remove: PIN_COVERAGE, PIN_CONSUMPTION_COVERAGE, EDGE_REALIZATION, NO_INLINED_ATOM_LOGIC, ARCH_DRIFT_PASS, TEST_PIN_ALIGNMENT.
#     - GateSpec keeps mode/severity/threshold/params; PromotionGateConfig keeps single global gate map (no per-layer config).
#     - Gates organized by aspect, run within three phases. Some hard verifiers
#       (ALL_TESTS_PASS, contract verifiers) are required in multiple phases:
#       - Libraries phase: library verifiers + ALL_TESTS_PASS (hard) + LLM gap scans (soft).
#       - Architecture phase: shape matching + contract verifiers + integration tests + ALL_TESTS_PASS (hard) + L2 reviewers (soft).
#       - Quality phase: ALL_TESTS_PASS + all contract verifiers + style checks (hard) + quality reviewers (soft).
#       - Gate execution policy maps gate → list of phases it applies to (not 1:1).
#   Interface contracts:
#     - def default() -> PromotionGateConfig sets deterministic hard gates required and advisory defaults for soft signals.
#     - def get_gate(gate_id: GateId) -> GateSpec
#   Control flow:
#     1. Define severity map for new gate IDs.
#     2. Merge TESTS_PASS semantics into ALL_TESTS_PASS.
#     3. Assign advisory mode to CALL_GRAPH_CONNECTED and NO_STUB_FUNCTIONS by default.
#     4. Each phase runs its own PromotionLoop with IMPLEMENT step — all phases edit code.
#     5. Phases are forward-only (Libraries -> Architecture -> Quality); no backtracking.
#     6. Phase-local remediation if within authority; block if outside authority.
#   Error handling:
#     - Unknown gate_id in loaded config -> ignore with warning or raise strict error based on policy flag.
#   Integration points:
#     - Used by compliance orchestrator and demotion triage routing table.
#     - Gate-to-phase mapping: gate → list of phases
#       (not 1:1; e.g. ALL_TESTS_PASS runs in all phases).
#   Test requirements:
#     - Enum contents exactly match new policy.
#     - Default mode/severity mapping is stable.
#     - Legacy gate IDs fail fast or are dropped deterministically.

"""Configuration schema for promotion gates and core enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


def _default_test_command() -> list[str]:
    """Build default test command from language module + algorithmic test dir."""
    from spec_manager.core.language import DEFAULT_TEST_COMMAND

    return [*DEFAULT_TEST_COMMAND, "tests/algorithmic/"]


class GateMode(Enum):
    """How a gate failure is treated."""

    REQUIRED = "required"  # Failure blocks promotion
    ADVISORY = "advisory"  # Failure produces warning but does not block


class GateSeverity(Enum):
    """Spec-level severity classification for each gate."""

    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"


class GateId(Enum):
    """Identifiers for each promotion gate check."""

    # IMPL(single-layer): GateId enum removes pin/layer-dependent gates:
    #   PIN_COVERAGE, PIN_CONSUMPTION_COVERAGE, EDGE_REALIZATION,
    #   NO_INLINED_ATOM_LOGIC, ARCH_DRIFT_PASS, TEST_PIN_ALIGNMENT.
    #   Adds SHAPE_VERIFIERS_PASS, IMPORT_BOUNDARY_CHECK, SHAPE_DRIFT_RESOLVED.
    #   TESTS_PASS is fully merged into ALL_TESTS_PASS.
    # Additional evidence gates
    NO_REMAINING_COMMENTS = "no_remaining_comments"
    NO_STUB_FUNCTIONS = "no_stub_functions"
    ALL_TESTS_PASS = "all_tests_pass"
    CALL_GRAPH_CONNECTED = "call_graph_connected"
    STORE_MONOGAMY = "store_monogamy"
    INTRODUCED_ALGORITHM_SPECS = "introduced_algorithm_specs"

    # L2 primary gates
    FUNCTION_RECOMPOSITION = "function_recomposition"
    NO_ORPHAN_COMPONENTS = "no_orphan_components"
    EVENT_HANDLER_COVERAGE = "event_handler_coverage"
    CONFIG_EXTERNALIZATION = "config_externalization"
    SHAPE_VERIFIERS_PASS = "shape_verifiers_pass"
    IMPORT_BOUNDARY_CHECK = "import_boundary_check"
    SHAPE_DRIFT_RESOLVED = "shape_drift_resolved"

    # Extended gates
    PROVENANCE_COMPLETE = "provenance_complete"
    ENTITY_COVERAGE = "entity_coverage"


# IMPL(single-layer): PhaseId is now a first-class type in config.py so gate policy
# and orchestration callers can share one forward-only phase vocabulary.
PhaseId = Literal["libraries", "architecture", "quality"]
ALL_PHASES: tuple[PhaseId, PhaseId, PhaseId] = ("libraries", "architecture", "quality")

# IMPL(single-layer): Replaces implicit layer-specific gate tables with a single
# gate execution policy: each gate maps to one or more phases it runs in.
GATE_PHASES: dict[GateId, tuple[PhaseId, ...]] = {
    GateId.NO_REMAINING_COMMENTS: ("quality",),
    GateId.NO_STUB_FUNCTIONS: ("libraries", "architecture", "quality"),
    GateId.ALL_TESTS_PASS: ALL_PHASES,
    GateId.CALL_GRAPH_CONNECTED: ("libraries", "architecture"),
    GateId.STORE_MONOGAMY: ("libraries", "architecture", "quality"),
    GateId.INTRODUCED_ALGORITHM_SPECS: ("libraries",),
    GateId.FUNCTION_RECOMPOSITION: ("architecture", "quality"),
    GateId.NO_ORPHAN_COMPONENTS: ("architecture", "quality"),
    GateId.EVENT_HANDLER_COVERAGE: ("architecture", "quality"),
    GateId.CONFIG_EXTERNALIZATION: ("architecture", "quality"),
    GateId.SHAPE_VERIFIERS_PASS: ALL_PHASES,
    GateId.IMPORT_BOUNDARY_CHECK: ALL_PHASES,
    GateId.SHAPE_DRIFT_RESOLVED: ("libraries", "architecture"),
    GateId.PROVENANCE_COMPLETE: ("architecture", "quality"),
    GateId.ENTITY_COVERAGE: ("quality",),
}


def _default_severity(gate_id: GateId) -> GateSeverity:
    """Return the spec-level default severity for a gate."""
    mapping: dict[GateId, GateSeverity] = {
        GateId.FUNCTION_RECOMPOSITION: GateSeverity.BLOCKER,
        GateId.NO_ORPHAN_COMPONENTS: GateSeverity.MAJOR,
        GateId.EVENT_HANDLER_COVERAGE: GateSeverity.MAJOR,
        GateId.CONFIG_EXTERNALIZATION: GateSeverity.MINOR,
        GateId.SHAPE_VERIFIERS_PASS: GateSeverity.BLOCKER,
        GateId.IMPORT_BOUNDARY_CHECK: GateSeverity.BLOCKER,
        GateId.SHAPE_DRIFT_RESOLVED: GateSeverity.BLOCKER,
        GateId.NO_REMAINING_COMMENTS: GateSeverity.BLOCKER,
        GateId.NO_STUB_FUNCTIONS: GateSeverity.BLOCKER,
        GateId.ALL_TESTS_PASS: GateSeverity.MAJOR,
        GateId.CALL_GRAPH_CONNECTED: GateSeverity.MAJOR,
        GateId.STORE_MONOGAMY: GateSeverity.MAJOR,
        GateId.INTRODUCED_ALGORITHM_SPECS: GateSeverity.MAJOR,
        GateId.PROVENANCE_COMPLETE: GateSeverity.MAJOR,
        GateId.ENTITY_COVERAGE: GateSeverity.MINOR,
    }
    return mapping.get(gate_id, GateSeverity.MAJOR)


def _default_mode_from_severity(severity: GateSeverity) -> GateMode:
    """Map spec severity to enforcement mode."""
    if severity == GateSeverity.MINOR:
        return GateMode.ADVISORY
    return GateMode.REQUIRED


@dataclass
class GateSpec:
    """Configuration for a single gate check.

    Attributes:
        gate_id: Which gate this configures.
        severity: Spec-level severity classification.
        mode: Whether failure blocks or warns.
        threshold: Optional numeric threshold (e.g., 0.0 for zero-tolerance,
            0.95 for 95% coverage). Interpretation depends on the gate.
        enabled: Whether this gate is active.
        params: Gate-specific parameters.
    """

    gate_id: GateId
    severity: GateSeverity | None = None
    mode: GateMode | None = None
    threshold: float = 0.0
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity is None:
            self.severity = _default_severity(self.gate_id)
        if self.mode is None:
            self.mode = _default_mode_from_severity(self.severity)


@dataclass
class PromotionGateConfig:
    """Full configuration for layer promotion gating.

    Attributes:
        gates: Per-gate configuration. Missing gates use defaults.
        algorithmic_roots: Directory paths treated as algorithmic code.
        architectural_roots: Directory paths treated as architectural code.
        atom_directories: Directories where atom (pin-function) files live.
        test_command: Command to run algorithmic tests.
        project_root: Root of the project being analyzed.
    """

    # IMPL(single-layer): This remains a single global gate map; per-layer gate
    # configuration tables are removed in favor of GATE_PHASES.
    gates: dict[GateId, GateSpec] = field(default_factory=dict)
    algorithmic_roots: list[str] = field(
        default_factory=lambda: [
            "algorithmic/atoms",
            "algorithmic/compositions",
            "algorithmic/stores",
            "algorithmic/shapes",
        ]
    )
    architectural_roots: list[str] = field(
        default_factory=lambda: [
            "architectural/services",
            "architectural/events",
            "architectural/middleware",
            "architectural/infrastructure",
        ]
    )
    atom_directories: list[str] = field(
        default_factory=lambda: ["algorithmic/atoms", "algorithmic/shapes"]
    )
    test_command: list[str] = field(default_factory=lambda: _default_test_command())
    project_root: str = "."

    def get_gate(self, gate_id: GateId) -> GateSpec:
        """Get gate spec, returning default if not configured."""
        if gate_id in self.gates:
            return self.gates[gate_id]
        return GateSpec(gate_id=gate_id)

    @classmethod
    def default(cls) -> PromotionGateConfig:
        """Create default configuration with severity-driven defaults."""
        config = cls()
        for gate_id in GateId:
            config.gates[gate_id] = GateSpec(gate_id=gate_id)
        # IMPL(single-layer): ALL_TESTS_PASS is hard/required across all phases.
        config.gates[GateId.ALL_TESTS_PASS].mode = GateMode.REQUIRED
        # Call graph connectivity and stub scanning are advisory routing signals.
        config.gates[GateId.CALL_GRAPH_CONNECTED].mode = GateMode.ADVISORY
        config.gates[GateId.NO_STUB_FUNCTIONS].mode = GateMode.ADVISORY
        # Shape/import verifiers are hard/required defaults.
        config.gates[GateId.SHAPE_VERIFIERS_PASS].mode = GateMode.REQUIRED
        config.gates[GateId.IMPORT_BOUNDARY_CHECK].mode = GateMode.REQUIRED
        config.gates[GateId.SHAPE_DRIFT_RESOLVED].mode = GateMode.REQUIRED
        # Entity coverage is advisory by default (new gate, not blocking).
        config.gates[GateId.ENTITY_COVERAGE].mode = GateMode.ADVISORY
        return config
