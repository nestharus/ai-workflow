"""Configuration schema for promotion gates and core enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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

    # Additional evidence gates
    NO_REMAINING_COMMENTS = "no_remaining_comments"
    NO_STUB_FUNCTIONS = "no_stub_functions"
    ALL_TESTS_PASS = "all_tests_pass"
    CALL_GRAPH_CONNECTED = "call_graph_connected"
    STORE_MONOGAMY = "store_monogamy"
    PIN_COVERAGE = "pin_coverage"
    INTRODUCED_ALGORITHM_SPECS = "introduced_algorithm_specs"

    # L2 primary gates
    NO_INLINED_ATOM_LOGIC = "no_inlined_atom_logic"
    FUNCTION_RECOMPOSITION = "function_recomposition"
    PIN_CONSUMPTION_COVERAGE = "pin_consumption_coverage"
    EDGE_REALIZATION = "edge_realization"
    NO_ORPHAN_COMPONENTS = "no_orphan_components"
    EVENT_HANDLER_COVERAGE = "event_handler_coverage"
    CONFIG_EXTERNALIZATION = "config_externalization"
    ARCH_DRIFT_PASS = "arch_drift_pass"

    # Extended gates
    PROVENANCE_COMPLETE = "provenance_complete"
    ENTITY_COVERAGE = "entity_coverage"
    TEST_PIN_ALIGNMENT = "test_pin_alignment"


def _default_severity(gate_id: GateId) -> GateSeverity:
    """Return the spec-level default severity for a gate."""
    mapping: dict[GateId, GateSeverity] = {
        GateId.NO_INLINED_ATOM_LOGIC: GateSeverity.BLOCKER,
        GateId.FUNCTION_RECOMPOSITION: GateSeverity.BLOCKER,
        GateId.PIN_CONSUMPTION_COVERAGE: GateSeverity.MAJOR,
        GateId.EDGE_REALIZATION: GateSeverity.MAJOR,
        GateId.NO_ORPHAN_COMPONENTS: GateSeverity.MAJOR,
        GateId.EVENT_HANDLER_COVERAGE: GateSeverity.MAJOR,
        GateId.CONFIG_EXTERNALIZATION: GateSeverity.MINOR,
        GateId.ARCH_DRIFT_PASS: GateSeverity.MAJOR,
        GateId.NO_REMAINING_COMMENTS: GateSeverity.BLOCKER,
        GateId.NO_STUB_FUNCTIONS: GateSeverity.BLOCKER,
        GateId.ALL_TESTS_PASS: GateSeverity.MAJOR,
        GateId.CALL_GRAPH_CONNECTED: GateSeverity.MAJOR,
        GateId.STORE_MONOGAMY: GateSeverity.MAJOR,
        GateId.PIN_COVERAGE: GateSeverity.MAJOR,
        GateId.INTRODUCED_ALGORITHM_SPECS: GateSeverity.MAJOR,
        GateId.PROVENANCE_COMPLETE: GateSeverity.MAJOR,
        GateId.ENTITY_COVERAGE: GateSeverity.MINOR,
        GateId.TEST_PIN_ALIGNMENT: GateSeverity.MINOR,
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
        # Tests and call graph connectivity are advisory by default.
        config.gates[GateId.ALL_TESTS_PASS].mode = GateMode.ADVISORY
        config.gates[GateId.CALL_GRAPH_CONNECTED].mode = GateMode.ADVISORY
        # Entity coverage is advisory by default (new gate, not blocking).
        config.gates[GateId.ENTITY_COVERAGE].mode = GateMode.ADVISORY
        # Test-pin alignment is advisory by default (early warning signal).
        config.gates[GateId.TEST_PIN_ALIGNMENT].mode = GateMode.ADVISORY
        return config
