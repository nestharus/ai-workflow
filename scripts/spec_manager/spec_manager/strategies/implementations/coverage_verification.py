"""Coverage verification strategy.

This strategy verifies that nothing was lost during a transformation
by comparing source units to target units.

It's typically applied after merging or extraction operations.
"""

from __future__ import annotations

from difflib import SequenceMatcher
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

_DEFAULT_COVERAGE_THRESHOLD = 0.95


class CoverageVerificationStrategy(Strategy):
    """Verifies coverage after transformations."""

    def __init__(
        self, definition: StrategyDefinition | None = None, tools: dict[str, Tool] | None = None
    ) -> None:
        """Initialize the strategy.

        Args:
            definition: Strategy definition from YAML.
            tools: Dictionary of available tools.
        """
        self.definition = definition
        self.tools = tools or {}

    @property
    def name(self) -> str:
        """Get strategy name."""
        return "coverage_verification"

    @property
    def purpose(self) -> str:
        """Get strategy purpose."""
        return "Verify nothing was lost during transformation"

    @property
    def risk_addressed(self) -> str:
        """Get addressed risk."""
        return "Content silently dropped during projection/merge"

    @property
    def phases(self) -> list[StrategyPhase]:
        """Get applicable phases."""
        return [StrategyPhase.VERIFICATION]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Always applies in verification phase."""
        return context.phase == StrategyPhase.VERIFICATION

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Execute coverage verification.

        Uses ATOM-BASED MEMBERSHIP with sequence-aware comparison,
        NOT set-based comparison (which destroys order and duplicates).
        """
        issues: list[str] = []
        actions: list[str] = []
        evidence_records: list[dict[str, Any]] = []
        membership_evidence: dict[str, dict[str, Any]] = {}  # atom_id -> match evidence
        coverage_threshold = _DEFAULT_COVERAGE_THRESHOLD
        if self.definition:
            coverage_threshold = self.definition.metadata.get(
                "coverage_threshold", _DEFAULT_COVERAGE_THRESHOLD
            )

        # Get source units from previous results
        source_units = context.previous_results.get("source_units", [])
        target_units = context.units

        if not source_units:
            # No source to compare - just check current status
            pending = [u for u in target_units if u.status == UnitStatus.PENDING]
            if pending:
                issues.append(f"{len(pending)} units still pending")
            return StrategyResult(
                units=target_units,
                actions_taken=["Checked unit status"],
                issues=issues,
                metrics={"pending_count": len(pending)},
            )

        # ATOM-BASED MEMBERSHIP (preserves order and duplicates)
        # Convert to atoms with stable IDs
        source_atoms = self._units_to_atoms(source_units)
        target_atoms = self._units_to_atoms(target_units)

        # Use SequenceMatcher for sequence-aware comparison
        source_lines = [a["content"] for a in source_atoms]
        target_lines = [a["content"] for a in target_atoms]

        matcher = SequenceMatcher(None, source_lines, target_lines)

        matched_atoms: list[dict[str, Any]] = []
        unmatched_atoms: list[dict[str, Any]] = []
        fuzzy_matched_atoms: list[dict[str, Any]] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                # Exact match - record membership evidence
                for idx in range(i1, i2):
                    atom = source_atoms[idx]
                    matched_atoms.append(atom)
                    membership_evidence[atom["id"]] = {
                        "status": "matched",
                        "confidence": 1.0,
                        "method": "exact_match",
                        "target_index": j1 + (idx - i1),
                    }
                    actions.append(f"Atom {atom['id']}: Exact match")

            elif tag == "replace":
                # Content changed - check for fuzzy matches
                for idx in range(i1, i2):
                    atom = source_atoms[idx]
                    # Find best fuzzy match in replacement range
                    best_match = self._find_best_atom_match(
                        atom["content"], [target_atoms[j]["content"] for j in range(j1, j2)]
                    )
                    if best_match and best_match[1] > 0.8:
                        fuzzy_matched_atoms.append(atom)
                        membership_evidence[atom["id"]] = {
                            "status": "fuzzy_matched",
                            "confidence": best_match[1],
                            "method": "sequence_matcher",
                            "match_content": best_match[0][:50],
                        }
                        actions.append(f"Atom {atom['id']}: Fuzzy match ({best_match[1]:.0%})")
                    else:
                        unmatched_atoms.append(atom)
                        membership_evidence[atom["id"]] = {
                            "status": "unmatched",
                            "confidence": 0.0,
                            "method": "sequence_matcher",
                        }
                        issues.append(
                            f"Unmatched atom: {atom['id']} ({len(atom['content'])} chars)"
                        )

            elif tag == "delete":
                # Content deleted from source
                for idx in range(i1, i2):
                    atom = source_atoms[idx]
                    unmatched_atoms.append(atom)
                    membership_evidence[atom["id"]] = {
                        "status": "deleted",
                        "confidence": 0.0,
                        "method": "sequence_matcher",
                    }
                    issues.append(f"Deleted atom: {atom['id']}")

            # 'insert' operations are new content in target - not a coverage issue

        # Calculate coverage using atom counts (not set sizes)
        total_atoms = len(source_atoms)
        matched_count = len(matched_atoms) + len(fuzzy_matched_atoms)
        coverage = matched_count / total_atoms if total_atoms > 0 else 1.0
        unmatched_severity = "error" if coverage < coverage_threshold else "warning"

        for atom in unmatched_atoms:
            atom_id = atom["id"]
            evidence = membership_evidence.get(atom_id, {})
            evidence_records.append(
                {
                    "category": "coverage",
                    "type": "unmatched_atoms",
                    "severity": unmatched_severity,
                    "details": {
                        "atom_id": atom_id,
                        "status": evidence.get("status"),
                        "confidence": evidence.get("confidence"),
                        "method": evidence.get("method"),
                    },
                }
            )

        for atom in fuzzy_matched_atoms:
            atom_id = atom["id"]
            evidence = membership_evidence.get(atom_id, {})
            evidence_records.append(
                {
                    "category": "coverage",
                    "type": "fuzzy_match",
                    "severity": "warning",
                    "details": {
                        "atom_id": atom_id,
                        "confidence": evidence.get("confidence"),
                        "match_method": evidence.get("method"),
                    },
                }
            )

        if coverage < coverage_threshold:
            evidence_records.append(
                {
                    "category": "coverage",
                    "type": "low_coverage",
                    "severity": "error",
                    "details": {
                        "coverage_percent": coverage * 100,
                        "threshold": coverage_threshold * 100,
                        "unmatched_count": len(unmatched_atoms),
                    },
                }
            )

        if unmatched_atoms:
            actions.append(f"Found {len(unmatched_atoms)} unmatched atoms (remainder)")
        if fuzzy_matched_atoms:
            issues.append(
                f"{len(fuzzy_matched_atoms)} atoms matched via heuristic similarity scoring"
            )

        return StrategyResult(
            units=target_units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "source_atoms": total_atoms,
                "target_atoms": len(target_atoms),
                "exact_matched": len(matched_atoms),
                "fuzzy_matched": len(fuzzy_matched_atoms),
                "unmatched": len(unmatched_atoms),
                "coverage_percent": coverage * 100,
                "membership_evidence": membership_evidence,
            },
            evidence_records=evidence_records,
        )

    def _units_to_atoms(self, units: list[Any]) -> list[dict[str, Any]]:
        """Convert units to atoms with stable IDs."""
        atoms: list[dict[str, Any]] = []
        for unit in units:
            unit_id = getattr(unit, "id", str(id(unit)))
            for i, line in enumerate(unit.content.split("\n")):
                if line.strip():
                    atom_id = f"{unit_id}_L{i + 1}_{hash(line) % 10000:04d}"
                    atoms.append(
                        {"id": atom_id, "content": line, "unit_id": unit_id, "line_number": i + 1}
                    )
        return atoms

    def _find_best_atom_match(self, needle: str, candidates: list[str]) -> tuple[str, float] | None:
        """Find best matching content in candidate list (sequence-aware)."""
        if not candidates:
            return None

        best: str | None = None
        best_score = 0.0

        for candidate in candidates:
            score = SequenceMatcher(None, needle, candidate).ratio()
            if score > best_score:
                best_score = score
                best = candidate

        return (best, best_score) if best else None

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison."""
        # Remove extra whitespace
        text = " ".join(text.split())
        # Remove common formatting
        text = text.strip()
        return text.lower()

    def _find_best_match(self, needle: str, haystack: set[str]) -> tuple[str, float] | None:
        """Find best matching content in haystack."""
        best: str | None = None
        best_score = 0.0

        for candidate in haystack:
            score = SequenceMatcher(None, needle, candidate).ratio()
            if score > best_score:
                best_score = score
                best = candidate

        return (best, best_score) if best else None
