"""Downward flow: architectural issues -> atom fix -> re-verify.

Handles downward flow where architectural integration test failures
trace back to algorithmic atoms via pins, enabling targeted fixes
and re-verification.

Workflow (design doc Section 6):
1. Architectural integration test fails
2. Trace pin back to algorithmic atom
3. Fix atom function (shared, so algorithmic layer updates too)
4. Re-verify both layers
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .atoms import AtomRegistry
from .layout import BranchLayout
from .pins import PinRegistry
from .types import AtomDescriptor, PinProjection


@dataclass
class ArchitecturalIssue:
    """An issue detected in the architectural branch."""

    issue_id: str
    location: str  # file:class.method in architectural branch
    description: str
    test_name: str | None = None
    stack_trace: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "issue_id": self.issue_id,
            "location": self.location,
            "description": self.description,
            "test_name": self.test_name,
            "stack_trace": self.stack_trace,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArchitecturalIssue:
        """Deserialize from dictionary."""
        return cls(
            issue_id=data["issue_id"],
            location=data["location"],
            description=data["description"],
            test_name=data.get("test_name"),
            stack_trace=data.get("stack_trace"),
        )


@dataclass
class DownwardTraceResult:
    """Result of tracing an architectural issue back to atoms."""

    issue: ArchitecturalIssue
    traced_pins: list[PinProjection]  # Pins at the issue location
    traced_atoms: list[AtomDescriptor]  # Atoms reached via pin trace
    confidence: float  # How confident the trace is
    suggested_fix_location: str | None  # Where to look in algorithmic branch

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "issue": self.issue.to_dict(),
            "traced_pins": [p.to_dict() for p in self.traced_pins],
            "traced_atoms": [a.to_dict() for a in self.traced_atoms],
            "confidence": self.confidence,
            "suggested_fix_location": self.suggested_fix_location,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DownwardTraceResult:
        """Deserialize from dictionary."""
        return cls(
            issue=ArchitecturalIssue.from_dict(data["issue"]),
            traced_pins=[PinProjection.from_dict(p) for p in data["traced_pins"]],
            traced_atoms=[AtomDescriptor.from_dict(a) for a in data["traced_atoms"]],
            confidence=data["confidence"],
            suggested_fix_location=data.get("suggested_fix_location"),
        )


class DownwardFlowEngine:
    """Handles downward flow from architectural issues to atom fixes.

    Workflow (design doc Section 6):
    1. Architectural integration test fails
    2. Trace pin back to algorithmic atom
    3. Fix atom function (shared, so algorithmic layer updates too)
    4. Re-verify both layers
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

    def trace_issue(self, issue: ArchitecturalIssue) -> DownwardTraceResult:
        """Trace an architectural issue back to its algorithmic origin.

        Looks up the architectural location in the pin registry, then
        resolves the atom descriptor for each matched pin.

        Args:
            issue: The architectural issue to trace.

        Returns:
            A DownwardTraceResult with traced pins and atoms.
        """
        traced_pins: list[PinProjection] = []
        traced_atoms: list[AtomDescriptor] = []

        # Exact location match -- gather ALL pins at this location
        # (aggregation pins share the same architectural location)
        exact_match = False
        for p in self._pin_registry.list_all():
            if p.architectural_location == issue.location:
                exact_match = True
                traced_pins.append(p)
                atom = self._atom_registry.get(p.atom_id)
                if atom is not None and atom not in traced_atoms:
                    traced_atoms.append(atom)

        # Also try prefix matching for partial locations
        # (e.g., issue at "services/payment_service.py:PaymentService.process"
        #  might match pin at "services/payment_service.py:PaymentService")
        if not traced_pins:
            for p in self._pin_registry.list_all():
                if issue.location.startswith(
                    p.architectural_location
                ) or p.architectural_location.startswith(issue.location):
                    traced_pins.append(p)
                    atom = self._atom_registry.get(p.atom_id)
                    if atom is not None and atom not in traced_atoms:
                        traced_atoms.append(atom)

        # Compute confidence based on match quality
        confidence = (1.0 if exact_match else 0.7) if traced_pins else 0.0

        # Suggest fix location
        suggested_fix: str | None = None
        if traced_atoms:
            first_atom = traced_atoms[0]
            suggested_fix = f"atoms/{first_atom.file_path}"

        return DownwardTraceResult(
            issue=issue,
            traced_pins=traced_pins,
            traced_atoms=traced_atoms,
            confidence=confidence,
            suggested_fix_location=suggested_fix,
        )

    def verify_fix(self, atom_id: str) -> dict[str, bool]:
        """After fixing an atom, verify both branches.

        Checks that the atom file exists and that all pins referencing
        it are still valid (the architectural locations exist).

        Args:
            atom_id: The atom that was fixed.

        Returns:
            Dict of ``{"algorithmic": bool, "architectural": bool}``.
        """
        result = {"algorithmic": False, "architectural": False}

        # Check algorithmic side: atom exists in registry and file exists
        descriptor = self._atom_registry.get(atom_id)
        if descriptor is not None:
            atom_file = self._layout.atoms_dir / descriptor.file_path
            result["algorithmic"] = atom_file.exists()

        # Check architectural side: all pins for this atom point to
        # existing locations
        pins = self._pin_registry.get_architectural_locations(atom_id)
        if not pins:
            # No pins means the architectural side is trivially valid
            result["architectural"] = True
        else:
            arch_dir = self._layout.architectural_dir()
            all_valid = True
            for pin_fn in pins:
                # Extract file path portion from architectural_location
                location_file = pin_fn.architectural_location.split(":")[0]
                arch_file = arch_dir / location_file
                # A pin is valid only when the referenced file exists.
                if not arch_file.exists():
                    all_valid = False
                    break
            result["architectural"] = all_valid

        return result
