"""Configuration schema for promotion gates and core enums."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GateMode(Enum):
    """How a gate failure is treated."""

    REQUIRED = "required"  # Failure blocks promotion
    ADVISORY = "advisory"  # Failure produces warning but does not block


class GateId(Enum):
    """Identifiers for each promotion gate check."""

    NO_REMAINING_COMMENTS = "no_remaining_comments"
    NO_STUB_FUNCTIONS = "no_stub_functions"
    ALL_TESTS_PASS = "all_tests_pass"
    CALL_GRAPH_CONNECTED = "call_graph_connected"
    STORE_MONOGAMY = "store_monogamy"
    PIN_COVERAGE = "pin_coverage"
    INTRODUCED_ALGORITHM_SPECS = "introduced_algorithm_specs"
    NO_INLINED_ATOM_LOGIC = "no_inlined_atom_logic"
    FUNCTION_RECOMPOSITION = "function_recomposition"
    PROVENANCE_COMPLETE = "provenance_complete"
    ENTITY_COVERAGE = "entity_coverage"
    TEST_PIN_ALIGNMENT = "test_pin_alignment"


@dataclass
class GateSpec:
    """Configuration for a single gate check.

    Attributes:
        gate_id: Which gate this configures.
        mode: Whether failure blocks or warns.
        threshold: Optional numeric threshold (e.g., 0.0 for zero-tolerance,
            0.95 for 95% coverage). Interpretation depends on the gate.
        enabled: Whether this gate is active.
        params: Gate-specific parameters.
    """

    gate_id: GateId
    mode: GateMode = GateMode.REQUIRED
    threshold: float = 0.0
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)


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
    test_command: list[str] = field(
        default_factory=lambda: ["pytest", "tests/algorithmic/", "-x", "--tb=short"]
    )
    project_root: str = "."

    def get_gate(self, gate_id: GateId) -> GateSpec:
        """Get gate spec, returning default if not configured."""
        if gate_id in self.gates:
            return self.gates[gate_id]
        return GateSpec(gate_id=gate_id)

    @classmethod
    def default(cls) -> PromotionGateConfig:
        """Create default configuration with all gates required."""
        config = cls()
        for gate_id in GateId:
            config.gates[gate_id] = GateSpec(gate_id=gate_id)
        # Tests and call graph connectivity are advisory by default
        # (projects may not have tests or may have legitimately disconnected components)
        config.gates[GateId.ALL_TESTS_PASS].mode = GateMode.ADVISORY
        config.gates[GateId.CALL_GRAPH_CONNECTED].mode = GateMode.ADVISORY
        # Entity coverage is advisory by default (new gate, not blocking)
        config.gates[GateId.ENTITY_COVERAGE].mode = GateMode.ADVISORY
        # Test-pin alignment is advisory by default (early warning signal)
        config.gates[GateId.TEST_PIN_ALIGNMENT].mode = GateMode.ADVISORY
        return config
