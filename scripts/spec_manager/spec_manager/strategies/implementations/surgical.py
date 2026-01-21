"""Surgical decomposition strategy.

This strategy performs surgical, traceable edits on content:
- Resolve unambiguous references
- Split compound segments
- Project atomic prose to structured forms
- Record underspecifications

It spawns the spec-manager-surgeon agent for LLM-based decisions.
Coverage is maintained throughout - every byte of original is accounted for.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.core.coverage import (
    CoverageTracker,
    Fragment,
    FragmentDestination,
    FragmentStatus,
)
from spec_manager.core.provenance import GranularityLevel, SourceLocation, TrackedUnit, UnitType
from spec_manager.strategies.base import (
    ProcessingContext,
    Strategy,
    StrategyDefinition,
    StrategyPhase,
    StrategyResult,
    Tool,
)


@dataclass
class SurgeonResponse:
    """Parsed response from the surgeon agent."""

    operation: str
    success: bool
    result: dict[str, Any]
    raw_output: str


class SurgicalDecompositionStrategy(Strategy):
    """Performs surgical decomposition using the surgeon agent.

    This strategy:
    1. Initializes coverage tracking for each input
    2. Iteratively processes fragments
    3. Spawns surgeon agent for each decision
    4. Maintains 100% coverage throughout
    5. Stops when all fragments are projected or underspecified
    """

    def __init__(
        self,
        definition: StrategyDefinition | None = None,
        tools: dict[str, Tool] | None = None,
        agent_runner: str | None = None,
    ) -> None:
        self.definition = definition
        self.tools = tools or {}
        # Path to agent runner script (or use uv run)
        self.agent_runner = agent_runner or "uv run python -m scripts.agents"

    @property
    def name(self) -> str:
        return "surgical_decomposition"

    @property
    def purpose(self) -> str:
        return "Surgically decompose prose into structured forms with full traceability"

    @property
    def risk_addressed(self) -> str:
        return "Information loss during decomposition - every byte must be accounted for"

    @property
    def phases(self) -> list[StrategyPhase]:
        return [StrategyPhase.DECOMPOSITION, StrategyPhase.CLEANING]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Apply to any context with prose units."""
        return any(u.unit_type in (UnitType.PROSE, UnitType.UNKNOWN) for u in context.units)

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Execute surgical decomposition."""
        actions: list[str] = []
        issues: list[str] = []

        # Initialize coverage tracker
        tracker = CoverageTracker()

        # Group units by source file
        by_file: dict[str, list[TrackedUnit]] = {}
        for unit in context.units:
            file_path = unit.source.file
            if file_path not in by_file:
                by_file[file_path] = []
            by_file[file_path].append(unit)

        # Initialize coverage for each file
        for file_path, units in by_file.items():
            # Combine units into full content for coverage
            full_content = "\n\n".join(u.content for u in units)
            tracker.initialize(file_path, full_content)

        # Process fragments iteratively
        max_iterations = 100
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Find a prose fragment to process
            fragment = self._find_next_fragment(tracker)
            if not fragment:
                break  # All done

            # Spawn surgeon agent to decide what to do
            response = self._call_surgeon(fragment, tracker)

            if not response.success:
                issues.append(f"Surgeon failed on {fragment.id}: {response.raw_output}")
                continue

            # Apply the surgeon's decision
            action = self._apply_surgeon_response(tracker, fragment, response)
            if action:
                actions.append(action)

        # Verify coverage
        output_units: list[TrackedUnit] = []
        for file_path in by_file:
            complete, gaps = tracker.verify_coverage(file_path)
            if not complete:
                issues.append(f"Coverage gap in {file_path}: {gaps}")

            # Convert fragments back to TrackedUnits
            for frag in tracker.get_leaves(file_path):
                unit = self._fragment_to_unit(frag)
                output_units.append(unit)

        # Build metrics
        metrics = {
            "iterations": iteration,
            "coverage_reports": {fp: tracker.get_coverage_report(fp) for fp in by_file},
        }

        return StrategyResult(
            units=output_units,
            actions_taken=actions,
            issues=issues,
            metrics=metrics,
            should_repeat=False,
        )

    def _find_next_fragment(self, tracker: CoverageTracker) -> Fragment | None:
        """Find next prose fragment to process."""
        for fragment in tracker.fragments.values():
            if fragment.is_leaf and fragment.status == FragmentStatus.PROSE:
                return fragment
        return None

    def _call_surgeon(
        self,
        fragment: Fragment,
        tracker: CoverageTracker,
    ) -> SurgeonResponse:
        """Spawn the surgeon agent to decide what to do with a fragment.

        The agent is called via subprocess to maintain isolation.
        """
        # Build context from nearby fragments
        context_fragments = self._get_context(tracker, fragment)
        context_text = "\n---\n".join(f.content for f in context_fragments)

        # Build the prompt for the surgeon
        prompt = f"""Analyze this fragment and decide what operation to perform.

FRAGMENT ID: {fragment.id}
FRAGMENT CONTENT:
{fragment.content}

SURROUNDING CONTEXT:
{context_text}

Decide ONE of:
1. resolve_reference - If there's an unambiguous pronoun/reference to resolve
2. split - If this is compound and should be split into atomic parts
3. project - If this is atomic enough to project to a structured form
4. underspecified - If there's unresolvable ambiguity

Output your decision as JSON:
{{"operation": "...", "details": {{...}}}}
"""

        try:
            # Call the surgeon agent
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "scripts.agents",
                    "spec-manager-surgeon",
                    prompt,
                ],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=Path(__file__).parent.parent.parent.parent.parent,  # Project root
            )

            output = result.stdout.strip()

            # Parse the response
            # Look for JSON in the output
            try:
                # Find JSON object in output
                start = output.find("{")
                end = output.rfind("}") + 1
                if start >= 0 and end > start:
                    json_str = output[start:end]
                    data = json.loads(json_str)
                    return SurgeonResponse(
                        operation=data.get("operation", "unknown"),
                        success=True,
                        result=data.get("details", {}),
                        raw_output=output,
                    )
            except json.JSONDecodeError:
                pass

            # Fallback: try to detect operation from text
            output_lower = output.lower()
            if "underspecified" in output_lower or "ambiguous" in output_lower:
                return SurgeonResponse(
                    operation="underspecified",
                    success=True,
                    result={"reason": "Detected ambiguity"},
                    raw_output=output,
                )
            elif "split" in output_lower:
                return SurgeonResponse(
                    operation="split",
                    success=True,
                    result={},
                    raw_output=output,
                )

            return SurgeonResponse(
                operation="unknown",
                success=False,
                result={},
                raw_output=output,
            )

        except subprocess.TimeoutExpired:
            return SurgeonResponse(
                operation="timeout",
                success=False,
                result={},
                raw_output="Agent timed out",
            )
        except Exception as e:
            return SurgeonResponse(
                operation="error",
                success=False,
                result={},
                raw_output=str(e),
            )

    def _apply_surgeon_response(
        self,
        tracker: CoverageTracker,
        fragment: Fragment,
        response: SurgeonResponse,
    ) -> str | None:
        """Apply the surgeon's decision to the fragment."""
        op = response.operation
        details = response.result

        if op == "resolve_reference":
            old_text = details.get("old", "")
            new_text = details.get("new", "")
            target = details.get("target", "unknown")

            if old_text and new_text:
                tracker.resolve_reference(fragment.id, old_text, new_text, target)
                return f"Resolved '{old_text}' -> '{new_text}' in {fragment.id}"

        elif op == "split":
            # Find split points in the content
            split_points = details.get("split_points", [])
            if not split_points:
                # Default: split on sentence boundaries
                split_points = self._find_sentence_boundaries(fragment.content)

            if split_points:
                children = tracker.split(fragment.id, split_points)
                return f"Split {fragment.id} into {len(children)} parts"

        elif op == "project":
            form = details.get("form", "unknown")
            projected = details.get("content", fragment.content)
            raw_traces = details.get("traces", [])

            # Convert traces to proper format with original/projected mappings
            traces = []
            for t in raw_traces:
                if isinstance(t, dict):
                    traces.append(t)
                elif isinstance(t, (list, tuple)) and len(t) >= 2:
                    # Convert (original, projected) tuple to dict
                    traces.append(
                        {
                            "original": t[0],
                            "projected": t[1],
                        }
                    )

            tracker.project(fragment.id, form, projected, traces if traces else None)
            return f"Projected {fragment.id} to {form}"

        elif op == "underspecified":
            ambiguities = details.get("ambiguities", ["Unspecified ambiguity"])
            if isinstance(ambiguities, str):
                ambiguities = [ambiguities]

            tracker.mark_underspecified(fragment.id, ambiguities)
            return f"Marked {fragment.id} as underspecified: {ambiguities}"

        elif op == "resolve_order_dependency":
            # Resolve implicit order dependencies (then, next, after)
            old_text = details.get("old", "")
            new_text = details.get("new", "")
            target_id = details.get("target_id", "")
            dependency_type = details.get("type", "comes_after")

            if old_text and new_text:
                # Apply the text resolution
                tracker.resolve_reference(fragment.id, old_text, new_text, f"order:{target_id}")

            if target_id:
                # Add the order dependency
                if dependency_type == "comes_after":
                    tracker.add_order_dependency(fragment.id, comes_after_id=target_id)
                elif dependency_type == "comes_before":
                    tracker.add_order_dependency(fragment.id, comes_before_id=target_id)

                return f"Resolved order dependency in {fragment.id}: {dependency_type} {target_id}"

        elif op == "compose":
            # Compose multiple fragments into one projection
            source_ids = details.get("source_ids", [fragment.id])
            form = details.get("form", "unknown")
            content = details.get("content", "")
            raw_traces = details.get("traces", [])

            # Convert traces
            traces = []
            for t in raw_traces:
                if isinstance(t, dict):
                    traces.append(t)

            if len(source_ids) >= 2 and content:
                composite = tracker.compose_projection(
                    source_ids, form, content, traces if traces else None
                )
                return f"Composed {source_ids} into {composite.id} ({form})"

        elif op == "annotate_dependency":
            # Add a declaration annotation to make this fragment referenceable
            annotation_id = details.get("id", "")
            if annotation_id:
                fragment.declarations.append(annotation_id)
                fragment.record_edit("annotate_dependency", {"id": annotation_id})
                return f"Added declaration ({annotation_id}) to {fragment.id}"

        elif op == "mark_stuck":
            # Mark fragment as stuck on dependencies
            stuck_on = details.get("stuck_on", [])
            dependency_types = details.get("dependency_types", [])
            if stuck_on:
                tracker.mark_stuck(fragment.id, stuck_on, dependency_types)
                return f"Marked {fragment.id} as stuck on: {stuck_on}"

        elif op == "mark_mobile":
            # Mark fragment as mobile (all dependencies resolved)
            tracker.mark_mobile(fragment.id)
            return f"Marked {fragment.id} as mobile"

        elif op == "classify":
            # Classify fragment by information type
            dest_str = details.get("destination", "library")
            reason = details.get("reason", "")

            # Map string to enum
            dest_map = {
                "library": FragmentDestination.LIBRARY,
                "evidence": FragmentDestination.EVIDENCE,
                "gap": FragmentDestination.GAP,
                "decision": FragmentDestination.DECISION,
                "discard": FragmentDestination.DISCARD,
            }
            destination = dest_map.get(dest_str, FragmentDestination.LIBRARY)

            if destination == FragmentDestination.DECISION:
                # Decision needs alternatives and tradeoff
                decision = details.get("decision", "")
                alternatives = details.get("alternatives", [])
                tradeoff = details.get("tradeoff", "")
                if decision and alternatives:
                    tracker.mark_as_decision(fragment.id, decision, alternatives, tradeoff)
                    return f"Classified {fragment.id} as decision: {decision}"
            elif destination == FragmentDestination.DISCARD:
                tracker.mark_as_noise(fragment.id, reason)
                return f"Classified {fragment.id} as noise: {reason}"
            else:
                tracker.classify_fragment(fragment.id, destination, reason)
                return f"Classified {fragment.id} as {dest_str}: {reason}"

        elif op == "link":
            # Link fragments to establish relationships
            links = details.get("links", [])
            results = []
            for link in links:
                link_type = link.get("type", "")
                from_id = link.get("from", "")
                to_id = link.get("to", "")

                if link_type == "spec_to_invariant" and from_id and to_id:
                    tracker.link_to_invariant(from_id, to_id)
                    results.append(f"{from_id} → invariant {to_id}")
                elif link_type == "evidence_for" and from_id and to_id:
                    tracker.link_evidence(from_id, to_id)
                    results.append(f"{from_id} → evidence for {to_id}")
                elif link_type == "decision_for" and from_id and to_id:
                    frag = tracker.fragments.get(from_id)
                    if frag:
                        frag.decision_for = to_id
                        frag.record_edit("link_decision", {"decision_for": to_id})
                    results.append(f"{from_id} → decision for {to_id}")

            if results:
                return f"Linked: {', '.join(results)}"

        return None

    def _get_context(
        self,
        tracker: CoverageTracker,
        fragment: Fragment,
        window: int = 2,
    ) -> list[Fragment]:
        """Get surrounding fragments for context."""
        # Get all leaves from same file
        leaves = tracker.get_leaves(fragment.source_file)

        # Sort by position
        leaves.sort(key=lambda f: f.source_spans[0].start if f.source_spans else 0)

        # Find fragment index
        try:
            idx = next(i for i, f in enumerate(leaves) if f.id == fragment.id)
        except StopIteration:
            return []

        # Get window around it
        start = max(0, idx - window)
        end = min(len(leaves), idx + window + 1)

        return [f for f in leaves[start:end] if f.id != fragment.id]

    def _find_sentence_boundaries(self, text: str) -> list[int]:
        """Find sentence boundaries for splitting."""
        import re

        boundaries = []
        for m in re.finditer(r"[.!?]\s+", text):
            boundaries.append(m.end())
        return boundaries

    def _fragment_to_unit(self, fragment: Fragment) -> TrackedUnit:
        """Convert a fragment back to a TrackedUnit."""
        # Determine unit type from fragment status
        if fragment.status == FragmentStatus.PROJECTED:
            # Map projected form to unit type
            form_to_type = {
                "algorithm": UnitType.ALGORITHM,
                "math": UnitType.MATH,
                "proof": UnitType.PROOF,
                "data_structure": UnitType.DATA_STRUCTURE,
                "invariant": UnitType.INVARIANT,
                "pseudocode": UnitType.PSEUDOCODE,
            }
            unit_type = form_to_type.get(fragment.projected_form or "", UnitType.UNKNOWN)
            content = fragment.projected_content or fragment.content
        elif fragment.status == FragmentStatus.UNDERSPECIFIED:
            unit_type = UnitType.GAP  # Underspecification is a gap
            content = fragment.content
        else:
            unit_type = UnitType.PROSE
            content = fragment.content

        # Build source location from spans
        spans = fragment.source_spans
        line_start = spans[0].start if spans else 0
        line_end = spans[-1].end if spans else 0

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        return TrackedUnit(
            id=fragment.id,
            content=content,
            unit_type=unit_type,
            source=SourceLocation(
                file=fragment.source_file,
                line_start=line_start,
                line_end=line_end,
            ),
            introduced_by="surgical",
            granularity=GranularityLevel.CLAUSE,
            content_hash=content_hash,
            metadata={
                "fragment_status": fragment.status.value,
                "ambiguities": fragment.ambiguities,
                "edits": fragment.edits,
            },
        )
