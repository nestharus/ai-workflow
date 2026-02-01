"""Line membership strategy.

Tracks line-level membership to ensure every line is accounted for.
"""

from __future__ import annotations

from typing import Any

from spec_manager.core.provenance import UnitStatus
from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)


class LineMembershipStrategy(Strategy):
    """Track source-to-target line mapping."""

    def __init__(
        self, definition: StrategyDefinition | None = None, tools: dict[str, Tool] | None = None
    ) -> None:
        self.definition = definition
        self.tools = tools or {}

    @property
    def name(self) -> str:
        return "line_membership"

    @property
    def purpose(self) -> str:
        return "Track source-to-target line mapping to ensure every line is accounted for"

    @property
    def risk_addressed(self) -> str:
        return "Lines dropped without notice during transformation"

    @property
    def phases(self) -> list[StrategyPhase]:
        return [StrategyPhase.VERIFICATION, StrategyPhase.CLEANING]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Always applies in verification or cleaning phases."""
        return context.phase in (StrategyPhase.VERIFICATION, StrategyPhase.CLEANING)

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Execute line membership tracking."""
        actions: list[str] = []
        issues: list[str] = []

        atoms = self._units_to_atoms(context.units)

        mapped_atoms = 0
        for atom in atoms:
            unit = atom["unit"]
            atom_id = atom["id"]
            if unit.target:
                target_id = str(unit.target)
                unit.add_membership(
                    target_id,
                    rationale="line-level mapping",
                    confidence=1.0,
                    method="exact",
                )
                actions.append(f"Mapped atom {atom_id} to {target_id}")
                mapped_atoms += 1
            else:
                if unit.status == UnitStatus.DROPPED:
                    reason = unit.drop_reason or "dropped"
                    actions.append(f"Dropped atom {atom_id}: {reason}")
                else:
                    issues.append(f"Unmapped atom: {atom_id}")

        total_atoms = len(atoms)
        coverage = mapped_atoms / total_atoms if total_atoms > 0 else 1.0

        return StrategyResult(
            units=context.units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "total_atoms": total_atoms,
                "mapped_atoms": mapped_atoms,
                "coverage_percent": coverage * 100,
            },
        )

    def _units_to_atoms(self, units: list[Any]) -> list[dict[str, Any]]:
        """Convert units to line-level atoms with stable IDs."""
        atoms: list[dict[str, Any]] = []
        for unit in units:
            unit_id = getattr(unit, "id", str(id(unit)))
            for line_number, line in enumerate(unit.content.split("\n"), start=1):
                if not line.strip():
                    continue
                atom_id = f"{unit_id}_L{line_number}_{hash(line) % 10000:04d}"
                atoms.append(
                    {
                        "id": atom_id,
                        "content": line,
                        "unit_id": unit_id,
                        "line_number": line_number,
                        "unit": unit,
                    }
                )
        return atoms
