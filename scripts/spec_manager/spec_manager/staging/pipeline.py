"""
Strategy-based staging pipeline.

This module integrates the strategy framework with the staging phase,
providing multi-pass iteration until convergence.

Key principles:
1. Patches are IMMUTABLE - never modified
2. Intermediate state is stored in .workspace/staging/
3. Strategies are run iteratively until convergence
4. Evolution triggers create new strategies when stuck
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.core.provenance import (
    ProvenanceTracker,
    TrackedUnit,
    UnitType,
    UnitStatus,
    SourceLocation,
    LineageTable,
    GranularityLevel,
)
from spec_manager.strategies.base import (
    ProcessingContext,
    StrategyPhase,
    StrategyResult,
)
from spec_manager.strategies.registry import StrategyRegistry


@dataclass
class PassResult:
    """Result of a single pass through the pipeline."""

    pass_number: int
    units: list[TrackedUnit]
    strategies_applied: list[str]
    actions_taken: list[str]
    issues: list[str]
    metrics: dict[str, Any]

    # Convergence indicators
    units_before: int
    units_after: int
    prose_ratio_before: float
    prose_ratio_after: float

    @property
    def converged(self) -> bool:
        """Check if this pass shows convergence."""
        # Convergence if no change in units and prose ratio
        return (
            self.units_before == self.units_after and
            abs(self.prose_ratio_before - self.prose_ratio_after) < 0.01
        )


@dataclass
class PipelineResult:
    """Result of the full staging pipeline."""

    passes: list[PassResult]
    final_units: list[TrackedUnit]
    lineage: LineageTable

    # Summary metrics
    total_input_units: int
    total_output_units: int
    strategies_used: list[str]
    evolution_triggers: list[str]
    gaps_detected: list[dict[str, Any]]

    @property
    def converged(self) -> bool:
        """Check if pipeline converged."""
        return len(self.passes) > 0 and self.passes[-1].converged

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        return {
            'passes': [
                {
                    'pass_number': p.pass_number,
                    'strategies_applied': p.strategies_applied,
                    'actions_taken': p.actions_taken,
                    'issues': p.issues,
                    'metrics': p.metrics,
                    'units_before': p.units_before,
                    'units_after': p.units_after,
                    'prose_ratio_before': p.prose_ratio_before,
                    'prose_ratio_after': p.prose_ratio_after,
                    'converged': p.converged,
                }
                for p in self.passes
            ],
            'total_input_units': self.total_input_units,
            'total_output_units': self.total_output_units,
            'strategies_used': self.strategies_used,
            'evolution_triggers': self.evolution_triggers,
            'gaps_detected': self.gaps_detected,
            'converged': self.converged,
            'lineage': self.lineage.to_dict(),
        }


class StagingPipeline:
    """
    Multi-pass staging pipeline using the strategy framework.

    Usage:
        pipeline = StagingPipeline(workspace_path)
        result = pipeline.run(patch_paths)

    The pipeline:
    1. Loads patches into TrackedUnits (immutable read)
    2. Runs CLEANING strategies in a loop until convergence
    3. Saves intermediate state after each pass
    4. Detects evolution triggers and proposes new strategies
    5. Returns final cleaned units for next phase
    """

    def __init__(
        self,
        workspace_path: Path,
        strategy_definitions_path: Path | None = None,
        max_passes: int = 10,
        llm_client: Any = None,
    ) -> None:
        self.workspace_path = workspace_path
        self.staging_dir = workspace_path / "staging"
        self.max_passes = max_passes
        self.llm_client = llm_client

        # Initialize strategy registry
        self.registry = StrategyRegistry()

        # Load strategy definitions
        if strategy_definitions_path is None:
            # Default to strategies/definitions relative to this package
            strategy_definitions_path = (
                Path(__file__).parent.parent / "strategies" / "definitions"
            )

        if strategy_definitions_path.exists():
            count = self.registry.load_from_directory(strategy_definitions_path)
            print(f"Loaded {count} strategy definitions")

        # Register built-in tools
        self._register_tools()

        # Provenance tracking
        self.tracker = ProvenanceTracker()
        self.lineage = LineageTable()

    def _register_tools(self) -> None:
        """Register tools that strategies can use."""
        # Basic tools - strategies will use these
        self.registry.register_tool('split_sentences', self._tool_split_sentences)
        self.registry.register_tool('extract_ids', self._tool_extract_ids)
        self.registry.register_tool('normalize_whitespace', self._tool_normalize_whitespace)

    def _tool_split_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        import re
        # Simple sentence splitting
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _tool_extract_ids(self, text: str) -> list[str]:
        """Extract ID patterns from text."""
        import re
        patterns = [
            r'\(\[=([^\]]+)\]\)',           # Declarations
            r'\(@\[([+=])([^\]]+)\]\)',     # References
            r'\bAlgorithm\s+(\d+)\b',       # Algorithm N
            r'\b(P\d+I\d+|P\d+C\d+)\b',     # P#I#, P#C#
            r'\b(D\d+|G\d+)\b',             # D#, G#
        ]
        ids = []
        for pattern in patterns:
            ids.extend(re.findall(pattern, text))
        return list(set(ids))

    def _tool_normalize_whitespace(self, text: str) -> str:
        """Normalize whitespace in text."""
        import re
        text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 newlines
        text = re.sub(r'[ \t]+', ' ', text)     # Single spaces
        return text.strip()

    def run(self, patch_paths: list[Path]) -> PipelineResult:
        """
        Run the staging pipeline on patches.

        Args:
            patch_paths: List of paths to patch files (IMMUTABLE - never modified)

        Returns:
            PipelineResult with final units and metrics
        """
        # Ensure staging directory exists
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Load patches into TrackedUnits
        units = self._load_patches(patch_paths)
        self._save_pass_state(0, units, "initial")

        total_input = len(units)
        all_strategies_used: set[str] = set()
        all_evolution_triggers: list[str] = []
        all_gaps: list[dict[str, Any]] = []
        passes: list[PassResult] = []

        prev_context: ProcessingContext | None = None

        # Step 2: Iterate until convergence
        for pass_num in range(1, self.max_passes + 1):
            print(f"\n--- Pass {pass_num} ---")

            # Calculate metrics before
            prose_ratio_before = self._calculate_prose_ratio(units)
            units_before = len(units)

            # Create processing context
            context = ProcessingContext(
                units=units,
                phase=StrategyPhase.CLEANING,
                config={'pass_number': pass_num},
            )

            # Get applicable strategies
            applicable = self.registry.get_applicable(context)

            if not applicable:
                print("No applicable strategies found")
                # Check for evolution triggers
                if prev_context:
                    triggers = self.registry.check_evolution_triggers(context, prev_context)
                    if triggers:
                        all_evolution_triggers.extend(triggers)
                        # Capture gap and propose new strategy
                        gap = self._handle_evolution_trigger(context, triggers)
                        if gap:
                            all_gaps.append(gap)
                break

            # Run each applicable strategy
            pass_strategies: list[str] = []
            pass_actions: list[str] = []
            pass_issues: list[str] = []
            pass_metrics: dict[str, Any] = {}

            for strategy in applicable:
                print(f"  Running strategy: {strategy.name}")
                pass_strategies.append(strategy.name)
                all_strategies_used.add(strategy.name)

                try:
                    result = strategy.execute(context)

                    # Update units with strategy output
                    units = result.units
                    context.units = units  # Update context for next strategy

                    # Record lineage
                    self._record_strategy_lineage(strategy.name, result)

                    pass_actions.extend(result.actions_taken)
                    pass_issues.extend(result.issues)
                    pass_metrics[strategy.name] = result.metrics

                    if result.should_repeat:
                        print(f"    Strategy {strategy.name} requests repeat")

                except Exception as e:
                    print(f"    Strategy {strategy.name} failed: {e}")
                    pass_issues.append(f"{strategy.name} failed: {e}")

            # Calculate metrics after
            prose_ratio_after = self._calculate_prose_ratio(units)
            units_after = len(units)

            # Create pass result
            pass_result = PassResult(
                pass_number=pass_num,
                units=units,
                strategies_applied=pass_strategies,
                actions_taken=pass_actions,
                issues=pass_issues,
                metrics=pass_metrics,
                units_before=units_before,
                units_after=units_after,
                prose_ratio_before=prose_ratio_before,
                prose_ratio_after=prose_ratio_after,
            )
            passes.append(pass_result)

            # Save intermediate state
            self._save_pass_state(pass_num, units, "pass")

            print(f"  Units: {units_before} -> {units_after}")
            print(f"  Prose ratio: {prose_ratio_before:.1%} -> {prose_ratio_after:.1%}")
            print(f"  Actions: {len(pass_actions)}")

            # Check for convergence
            if pass_result.converged:
                print(f"  Converged at pass {pass_num}")
                break

            # Check for evolution triggers
            if prev_context:
                triggers = self.registry.check_evolution_triggers(context, prev_context)
                if triggers:
                    print(f"  Evolution triggers: {triggers}")
                    all_evolution_triggers.extend(triggers)

                    # Try to evolve
                    gap = self._handle_evolution_trigger(context, triggers)
                    if gap:
                        all_gaps.append(gap)

            prev_context = context

        # Save final state
        self._save_pass_state(-1, units, "final")

        return PipelineResult(
            passes=passes,
            final_units=units,
            lineage=self.lineage,
            total_input_units=total_input,
            total_output_units=len(units),
            strategies_used=list(all_strategies_used),
            evolution_triggers=all_evolution_triggers,
            gaps_detected=all_gaps,
        )

    def _load_patches(self, patch_paths: list[Path]) -> list[TrackedUnit]:
        """
        Load patches into TrackedUnits.

        IMPORTANT: This only READS patches, never modifies them.
        """
        all_units: list[TrackedUnit] = []

        for path in patch_paths:
            if not path.exists():
                print(f"Warning: Patch not found: {path}")
                continue

            content = path.read_text(encoding="utf-8")
            patch_id = path.stem  # e.g., "p1", "p2"

            # Use ProvenanceTracker to extract units
            units = self.tracker.extract_units_from_file(
                content=content,
                file_path=str(path),
                patch_id=patch_id
            )

            all_units.extend(units)
            print(f"Loaded {len(units)} units from {path.name}")

        return all_units

    def _calculate_prose_ratio(self, units: list[TrackedUnit]) -> float:
        """Calculate the ratio of prose units."""
        if not units:
            return 0.0
        prose_count = sum(
            1 for u in units
            if u.unit_type in (UnitType.PROSE, UnitType.UNKNOWN)
        )
        return prose_count / len(units)

    def _record_strategy_lineage(self, strategy_name: str, result: StrategyResult) -> None:
        """Record lineage edges from strategy execution."""
        # For each action that created new units, record lineage
        for action in result.actions_taken:
            if "Split" in action or "Decomposed" in action:
                # Parse action to extract unit IDs if possible
                # This is a simplified version - real impl would have structured data
                self.lineage.add_edge(
                    from_unit="source",  # Would need actual IDs
                    to_unit="target",
                    transformation=strategy_name,
                    details={'action': action}
                )

    def _handle_evolution_trigger(
        self,
        context: ProcessingContext,
        triggers: list[str]
    ) -> dict[str, Any] | None:
        """Handle an evolution trigger by proposing a new strategy."""

        # Get stuck units (prose that isn't being processed)
        stuck_units = [
            u for u in context.units
            if u.unit_type in (UnitType.PROSE, UnitType.UNKNOWN)
            and u.status == UnitStatus.PENDING
        ]

        if not stuck_units:
            return None

        # Capture the gap
        gap_evidence = self.registry.capture_strategy_gap(
            context=context,
            failure_mode=triggers[0],
            failing_inputs=stuck_units[:5]
        )

        # Try to propose a new strategy via LLM
        if self.llm_client:
            proposed = self.registry.propose_strategy_via_llm(
                gap_evidence=gap_evidence,
                llm_client=self.llm_client
            )

            if proposed:
                # Register as experimental
                self.registry.register_experimental_from_gap(gap_evidence)
                print(f"Proposed new strategy: {proposed.name}")

        return {
            'failure_mode': gap_evidence.failure_mode,
            'stuck_units': len(stuck_units),
            'proposed_strategy': gap_evidence.proposed_strategy.name if gap_evidence.proposed_strategy else None,
        }

    def _save_pass_state(
        self,
        pass_num: int,
        units: list[TrackedUnit],
        state_type: str
    ) -> Path:
        """
        Save intermediate state to workspace.

        Creates: .workspace/staging/pass_{N}/units.json
        Or: .workspace/staging/final/units.json
        """
        if pass_num == -1 or state_type == "final":
            pass_dir = self.staging_dir / "final"
        elif state_type == "initial":
            pass_dir = self.staging_dir / "initial"
        else:
            pass_dir = self.staging_dir / f"pass_{pass_num}"

        pass_dir.mkdir(parents=True, exist_ok=True)

        # Serialize units
        units_data = []
        for unit in units:
            units_data.append({
                'id': unit.id,
                'content': unit.content,
                'unit_type': unit.unit_type.value,
                'source': {
                    'file': unit.source.file,
                    'line_start': unit.source.line_start,
                    'line_end': unit.source.line_end,
                    'patch_id': unit.source.patch_id,
                },
                'introduced_by': unit.introduced_by,
                'modified_by': unit.modified_by,
                'declarations': unit.declarations,
                'references': unit.references,
                'status': unit.status.value,
                'parents': unit.parents,
                'children': unit.children,
                'granularity': unit.granularity.value,
                'parent_unit_id': unit.parent_unit_id,
                'child_unit_ids': unit.child_unit_ids,
                'content_hash': unit.content_hash,
            })

        units_path = pass_dir / "units.json"
        with open(units_path, 'w', encoding='utf-8') as f:
            json.dump(units_data, f, indent=2)

        print(f"Saved {len(units)} units to {units_path}")
        return units_path

    def load_final_units(self) -> list[TrackedUnit]:
        """Load final units from workspace."""
        final_path = self.staging_dir / "final" / "units.json"

        if not final_path.exists():
            return []

        with open(final_path, 'r', encoding='utf-8') as f:
            units_data = json.load(f)

        units = []
        for data in units_data:
            unit = TrackedUnit(
                id=data['id'],
                content=data['content'],
                unit_type=UnitType(data['unit_type']),
                source=SourceLocation(
                    file=data['source']['file'],
                    line_start=data['source']['line_start'],
                    line_end=data['source']['line_end'],
                    patch_id=data['source'].get('patch_id'),
                ),
                introduced_by=data['introduced_by'],
                modified_by=data.get('modified_by', []),
                declarations=data.get('declarations', []),
                references=data.get('references', []),
                status=UnitStatus(data.get('status', 'pending')),
                parents=data.get('parents', []),
                children=data.get('children', []),
                granularity=GranularityLevel(data.get('granularity', GranularityLevel.SECTION.value)),
                parent_unit_id=data.get('parent_unit_id'),
                child_unit_ids=data.get('child_unit_ids', []),
                content_hash=data.get('content_hash'),
            )
            units.append(unit)

        return units
