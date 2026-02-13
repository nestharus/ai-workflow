"""Segment coverage tracking.

Ensures every byte of the original content is accounted for during
surgical decomposition. Fragments can be moved, split, duplicated,
and projected - but coverage must remain complete.

Key invariant: At any point, the union of all fragment traces must
cover 100% of the original content. No gaps, no losses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FragmentStatus(Enum):
    """Status of a fragment in the coverage map."""

    PROSE = "prose"  # Still prose, not yet projected
    STUCK = "stuck"  # Depends on context, cannot move yet
    MOBILE = "mobile"  # Self-contained, ready to project
    PROJECTED = "projected"  # Successfully projected to structured form
    UNDERSPECIFIED = "underspecified"  # Contains ambiguity, cannot project
    SPLIT = "split"  # Split into children (this fragment is parent)
    MERGED = "merged"  # Merged into another fragment
    COMPOSED = "composed"  # Composed into a multi-fragment projection
    DECISION = "decision"  # Rationale/tradeoff - moves to decision doc
    NOISE = "noise"  # Self-justifying content, adds nothing


class FragmentDestination(Enum):
    """Where a fragment should be routed after classification."""

    # Libraries folder - concrete specifications
    LIBRARY = "library"  # Algorithm, UX, data structure, invariant - the actual spec

    # Evidence folder - supports why the spec is correct
    EVIDENCE = "evidence"  # Math, proofs - evidence that spec is right

    # Gaps folder - things that need resolution
    GAP = "gap"  # Underspecification, needs resolution

    # Decisions folder - rationale for choices
    DECISION = "decision"  # Tradeoff rationale (why X over Y)

    # Discard - adds nothing
    DISCARD = "discard"  # Noise - circular justification, adds nothing


class DependencyType(Enum):
    """Types of context dependencies that make fragments stuck."""

    REFERENCE = "reference"  # Pronoun/reference (it, this, that)
    ORDER = "order"  # Sequence dependency (then, next, after)
    DEFINITION = "definition"  # Uses undefined term


@dataclass
class Span:
    """A span in the original content."""

    start: int  # Inclusive
    end: int  # Exclusive

    def __len__(self) -> int:
        return self.end - self.start

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Span) -> bool:
        return self.start <= other.start and other.end <= self.end

    def __repr__(self) -> str:
        return f"[{self.start}:{self.end}]"


@dataclass
class Fragment:
    """A fragment of content with traceability to original.

    Fragments form a tree: when split, the parent points to children.
    The leaves of the tree cover the original content exactly.

    Mobility: A fragment is "stuck" if it depends on surrounding context.
    We dislodge stuck fragments by resolving references and adding annotations.
    """

    id: str
    content: str
    status: FragmentStatus

    # Trace back to original
    source_file: str
    source_spans: list[Span]  # May be multiple if merged/reordered

    # Tree structure
    parent_id: str | None = None
    children_ids: list[str] = field(default_factory=list)

    # Annotations - enable mobility
    declarations: list[str] = field(default_factory=list)  # ([=ID]) - this fragment defines
    references: list[str] = field(default_factory=list)  # (@[+ID]) - this fragment references

    # Mobility tracking
    stuck_on: list[str] = field(default_factory=list)  # What this fragment depends on
    dependencies_resolved: list[str] = field(default_factory=list)  # Resolved dependencies

    # Order dependencies - "then" / "after" / sequence
    comes_after: list[str] = field(default_factory=list)  # IDs this must come after
    comes_before: list[str] = field(default_factory=list)  # IDs this must come before

    # Composition tracking - for multi-fragment projections
    composed_into: str | None = None  # ID of composite projection this is part of

    # Classification and routing
    destination: FragmentDestination | None = None  # Where this fragment should go

    # Relationships - every spec element is connected
    # Invariant → Spec → Evidence → Decision
    relates_to_invariant: str | None = None  # ID of invariant this satisfies
    evidence_for: str | None = None  # ID of spec item this proves
    decision_for: str | None = None  # ID of spec item this justifies

    # For projected fragments
    projected_form: str | None = None  # "algorithm", "math", "invariant", etc.
    projected_content: str | None = None

    # For underspecified fragments
    ambiguities: list[str] = field(default_factory=list)

    # Edit history
    edits: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        """Leaf fragments are the current state (not split/composed into other fragments)."""
        return len(self.children_ids) == 0 and self.composed_into is None

    @property
    def total_span_length(self) -> int:
        """Total length of original content this fragment traces to."""
        return sum(len(s) for s in self.source_spans)

    def record_edit(self, edit_type: str, details: dict[str, Any]) -> None:
        """Record an edit for traceability."""
        self.edits.append(
            {
                "type": edit_type,
                "details": details,
            }
        )


class CoverageTracker:
    """Tracks coverage of original content through transformations.

    Invariant: The leaf fragments must cover 100% of the original.

    Usage:
        tracker = CoverageTracker()
        tracker.initialize(file_path, content)

        # Split a fragment
        children = tracker.split(fragment_id, split_points)

        # Project a fragment
        tracker.project(fragment_id, form, projected_content)

        # Mark as underspecified
        tracker.mark_underspecified(fragment_id, ambiguities)

        # Verify coverage
        assert tracker.verify_coverage()
    """

    def __init__(self) -> None:
        self.fragments: dict[str, Fragment] = {}
        self.original_content: dict[str, str] = {}  # file -> content
        self.original_length: dict[str, int] = {}  # file -> length
        self._next_id = 1

    def _gen_id(self) -> str:
        """Generate unique fragment ID."""
        fid = f"frag_{self._next_id}"
        self._next_id += 1
        return fid

    def initialize(self, file_path: str, content: str) -> Fragment:
        """Initialize coverage for a file.

        Creates a single root fragment covering the entire file.
        """
        self.original_content[file_path] = content
        self.original_length[file_path] = len(content)

        root = Fragment(
            id=self._gen_id(),
            content=content,
            status=FragmentStatus.PROSE,
            source_file=file_path,
            source_spans=[Span(0, len(content))],
        )

        self.fragments[root.id] = root
        return root

    def split(
        self,
        fragment_id: str,
        split_points: list[int],
    ) -> list[Fragment]:
        """Split a fragment at the given points.

        Args:
            fragment_id: Fragment to split
            split_points: Offsets within fragment content to split at

        Returns:
            List of child fragments
        """
        parent = self.fragments[fragment_id]

        if not parent.is_leaf:
            raise ValueError(f"Cannot split non-leaf fragment {fragment_id}")

        points = sorted(set([0, *split_points, len(parent.content)]))

        children = []
        for i in range(len(points) - 1):
            start, end = points[i], points[i + 1]
            child_content = parent.content[start:end]

            # Map back to original spans
            child_spans = self._map_spans(parent.source_spans, start, end)

            child = Fragment(
                id=self._gen_id(),
                content=child_content,
                status=FragmentStatus.PROSE,
                source_file=parent.source_file,
                source_spans=child_spans,
                parent_id=parent.id,
            )

            self.fragments[child.id] = child
            children.append(child)
            parent.children_ids.append(child.id)

        parent.status = FragmentStatus.SPLIT
        parent.record_edit(
            "split", {"split_points": split_points, "children": [c.id for c in children]}
        )

        return children

    def _map_spans(self, parent_spans: list[Span], start: int, end: int) -> list[Span]:
        """Map a range within fragment content back to original spans."""
        result = []
        offset = 0

        for span in parent_spans:
            span_len = len(span)
            span_start_in_content = offset
            span_end_in_content = offset + span_len

            # Check if this span overlaps with [start, end)
            if span_end_in_content > start and span_start_in_content < end:
                # Calculate overlap
                overlap_start = max(start - span_start_in_content, 0)
                overlap_end = min(end - span_start_in_content, span_len)

                result.append(Span(span.start + overlap_start, span.start + overlap_end))

            offset += span_len

        return result

    def project(
        self,
        fragment_id: str,
        form: str,
        projected_content: str,
        traces: list[dict[str, Any]] | None = None,
    ) -> None:
        """Mark a fragment as projected to a structured form.

        Projection is a TRANSLATION from prose to structured form.
        The traces map each part of the projected content back to
        the original prose that it came from.

        Args:
            fragment_id: Fragment to project
            form: The structured form (e.g., "algorithm", "math", "invariant")
            projected_content: The projected content
            traces: List of trace mappings, each with:
                - original: The original prose text
                - projected: The projected structured text
                - original_span: (start, end) in original fragment
                - projected_span: (start, end) in projected content
        """
        fragment = self.fragments[fragment_id]

        if not fragment.is_leaf:
            raise ValueError(f"Cannot project non-leaf fragment {fragment_id}")

        # Validate traces cover the projection
        if traces:
            # Each trace should map original -> projected
            for trace in traces:
                if "original" not in trace or "projected" not in trace:
                    raise ValueError(f"Trace missing required fields: {trace}")

        fragment.status = FragmentStatus.PROJECTED
        fragment.projected_form = form
        fragment.projected_content = projected_content

        # Store projection traces for full traceability
        projection_record = {
            "type": "projection",
            "form": form,
            "original_content": fragment.content,
            "projected_content": projected_content,
            "traces": traces or [],
            # The entire original is covered by the projection
            "coverage": "complete" if traces else "untraced",
        }

        fragment.record_edit("project", projection_record)

    def mark_underspecified(
        self,
        fragment_id: str,
        ambiguities: list[str],
    ) -> None:
        """Mark a fragment as underspecified (contains unresolvable ambiguity).

        Args:
            fragment_id: Fragment to mark
            ambiguities: List of ambiguity descriptions
        """
        fragment = self.fragments[fragment_id]

        if not fragment.is_leaf:
            raise ValueError(f"Cannot mark non-leaf fragment {fragment_id}")

        fragment.status = FragmentStatus.UNDERSPECIFIED
        fragment.ambiguities = ambiguities
        fragment.record_edit("underspecified", {"ambiguities": ambiguities})

    def resolve_reference(
        self,
        fragment_id: str,
        old_text: str,
        new_text: str,
        reference_target: str,
    ) -> None:
        """Apply a reference resolution edit (translation).

        This is a TRANSLATION - the meaning is preserved, just made explicit.
        The trace maps the new text back to the original position.

        Args:
            fragment_id: Fragment to edit
            old_text: The reference text (e.g., "it")
            new_text: The resolved text (e.g., "a")
            reference_target: What it resolves to
        """
        fragment = self.fragments[fragment_id]

        if not fragment.is_leaf:
            raise ValueError(f"Cannot edit non-leaf fragment {fragment_id}")

        # Find position of old text
        pos = fragment.content.find(old_text)
        if pos == -1:
            raise ValueError(f"'{old_text}' not found in fragment {fragment_id}")

        # Apply the edit
        new_content = fragment.content[:pos] + new_text + fragment.content[pos + len(old_text) :]

        # Record the translation trace
        # The new text at position `pos` traces back to old text at same position
        translation_trace = {
            "type": "translation",
            "original_text": old_text,
            "translated_text": new_text,
            "position": pos,
            "original_span": (pos, pos + len(old_text)),
            "target": reference_target,
        }

        fragment.content = new_content
        fragment.record_edit(
            "resolve_reference",
            {
                "old": old_text,
                "new": new_text,
                "target": reference_target,
                "trace": translation_trace,
            },
        )

    def duplicate(self, fragment_id: str) -> Fragment:
        """Duplicate a fragment (for traceability when content appears in multiple places).

        Returns:
            New fragment with same content and traces
        """
        original = self.fragments[fragment_id]

        duplicate = Fragment(
            id=self._gen_id(),
            content=original.content,
            status=original.status,
            source_file=original.source_file,
            source_spans=original.source_spans.copy(),  # Same traces
            parent_id=original.parent_id,
        )

        self.fragments[duplicate.id] = duplicate
        duplicate.record_edit("duplicated_from", {"original_id": fragment_id})

        return duplicate

    def compose_projection(
        self,
        fragment_ids: list[str],
        form: str,
        projected_content: str,
        traces: list[dict[str, Any]] | None = None,
    ) -> Fragment:
        """Compose multiple fragments into a single projection.

        The projection inherits annotations from all source fragments,
        with deduplication of duplicate annotations.

        Args:
            fragment_ids: Fragments to compose
            form: The structured form (e.g., "algorithm", "math")
            projected_content: The projected content
            traces: Trace mappings from each source fragment

        Returns:
            New composite fragment with merged annotations
        """
        if len(fragment_ids) < 2:
            raise ValueError("Composition requires at least 2 fragments")

        # Collect all source data
        source_fragments = [self.fragments[fid] for fid in fragment_ids]

        # All fragments must be leaves and from same file
        for frag in source_fragments:
            if not frag.is_leaf:
                raise ValueError(f"Cannot compose non-leaf fragment {frag.id}")

        source_file = source_fragments[0].source_file
        if not all(f.source_file == source_file for f in source_fragments):
            raise ValueError("Cannot compose fragments from different files")

        # Merge spans from all sources
        merged_spans: list[Span] = []
        for frag in source_fragments:
            merged_spans.extend(frag.source_spans)
        merged_spans.sort(key=lambda s: s.start)

        # Collect and deduplicate annotations
        all_declarations: set[str] = set()
        all_references: set[str] = set()
        all_comes_after: set[str] = set()
        all_comes_before: set[str] = set()

        for frag in source_fragments:
            all_declarations.update(frag.declarations)
            all_references.update(frag.references)
            all_comes_after.update(frag.comes_after)
            all_comes_before.update(frag.comes_before)

        # Create the composite fragment
        composite = Fragment(
            id=self._gen_id(),
            content=projected_content,
            status=FragmentStatus.PROJECTED,
            source_file=source_file,
            source_spans=merged_spans,
            projected_form=form,
            projected_content=projected_content,
            declarations=list(all_declarations),
            references=list(all_references),
            comes_after=list(all_comes_after),
            comes_before=list(all_comes_before),
        )

        self.fragments[composite.id] = composite

        # Mark source fragments as composed
        for frag in source_fragments:
            frag.status = FragmentStatus.COMPOSED
            frag.composed_into = composite.id
            frag.record_edit(
                "composed",
                {
                    "composite_id": composite.id,
                    "other_sources": [f.id for f in source_fragments if f.id != frag.id],
                },
            )

        composite.record_edit(
            "compose_projection",
            {
                "source_ids": fragment_ids,
                "form": form,
                "traces": traces or [],
                "deduplicated_declarations": list(all_declarations),
                "deduplicated_references": list(all_references),
            },
        )

        return composite

    def add_order_dependency(
        self,
        fragment_id: str,
        comes_after_id: str | None = None,
        comes_before_id: str | None = None,
    ) -> None:
        """Add an order dependency to make a fragment mobile.

        Order dependencies resolve implicit sequence references like
        "then do X" or "after that, compute Y".

        Args:
            fragment_id: Fragment to annotate
            comes_after_id: ID this fragment must come after
            comes_before_id: ID this fragment must come before
        """
        fragment = self.fragments[fragment_id]

        if comes_after_id:
            if comes_after_id not in fragment.comes_after:
                fragment.comes_after.append(comes_after_id)
            fragment.record_edit(
                "add_order_dependency",
                {
                    "type": "comes_after",
                    "target_id": comes_after_id,
                },
            )

        if comes_before_id:
            if comes_before_id not in fragment.comes_before:
                fragment.comes_before.append(comes_before_id)
            fragment.record_edit(
                "add_order_dependency",
                {
                    "type": "comes_before",
                    "target_id": comes_before_id,
                },
            )

    def mark_mobile(self, fragment_id: str) -> None:
        """Mark a fragment as mobile (all dependencies resolved/annotated)."""
        fragment = self.fragments[fragment_id]

        if not fragment.is_leaf:
            raise ValueError(f"Cannot mark non-leaf fragment {fragment_id} as mobile")

        fragment.status = FragmentStatus.MOBILE
        fragment.record_edit(
            "mark_mobile",
            {
                "resolved_dependencies": fragment.dependencies_resolved,
                "order_after": fragment.comes_after,
                "order_before": fragment.comes_before,
            },
        )

    def mark_stuck(
        self,
        fragment_id: str,
        stuck_on: list[str],
        dependency_types: list[str] | None = None,
    ) -> None:
        """Mark a fragment as stuck on specific dependencies.

        Args:
            fragment_id: Fragment to mark
            stuck_on: List of dependency descriptions
            dependency_types: Types of dependencies (reference, order, definition)
        """
        fragment = self.fragments[fragment_id]

        if not fragment.is_leaf:
            raise ValueError(f"Cannot mark non-leaf fragment {fragment_id} as stuck")

        fragment.status = FragmentStatus.STUCK
        fragment.stuck_on = stuck_on
        fragment.record_edit(
            "mark_stuck",
            {
                "stuck_on": stuck_on,
                "dependency_types": dependency_types or [],
            },
        )

    def classify_fragment(
        self,
        fragment_id: str,
        destination: FragmentDestination,
        reason: str,
        is_tradeoff: bool = False,
        alternatives: list[str] | None = None,
    ) -> None:
        """Classify a fragment for routing to appropriate destination.

        Classification types:
        - SPEC: Projects to invariant, algorithm, data structure, etc.
        - GAP: Underspecification that needs resolution
        - DECISION_DOC: Tradeoff rationale (why X over Y)
        - DISCARD: Noise - circular justification that adds nothing

        Args:
            fragment_id: Fragment to classify
            destination: Where it should go
            reason: Why this classification
            is_tradeoff: True if this discusses a tradeoff (for decision docs)
            alternatives: Alternatives considered (for decision docs)
        """
        fragment = self.fragments[fragment_id]

        if not fragment.is_leaf:
            raise ValueError(f"Cannot classify non-leaf fragment {fragment_id}")

        fragment.destination = destination

        # Update status based on destination
        if destination == FragmentDestination.DISCARD:
            fragment.status = FragmentStatus.NOISE
        elif destination == FragmentDestination.DECISION:
            fragment.status = FragmentStatus.DECISION
        elif destination == FragmentDestination.GAP:
            fragment.status = FragmentStatus.UNDERSPECIFIED
        elif destination in (FragmentDestination.LIBRARY, FragmentDestination.EVIDENCE):
            # These will be projected before routing
            pass  # Status determined by project operation

        fragment.record_edit(
            "classify",
            {
                "destination": destination.value,
                "reason": reason,
                "is_tradeoff": is_tradeoff,
                "alternatives": alternatives or [],
            },
        )

    def mark_as_noise(
        self,
        fragment_id: str,
        reason: str,
    ) -> None:
        """Mark a fragment as noise (adds nothing to the spec).

        Noise patterns:
        - "It provides X" without comparing to alternatives
        - "Was this the right choice? Yes because..." (circular)
        - Justifying a decision that's already in an invariant
        - Meta-commentary about the writing process

        Args:
            fragment_id: Fragment to mark
            reason: Why this is noise
        """
        self.classify_fragment(
            fragment_id,
            FragmentDestination.DISCARD,
            reason,
        )

    def mark_as_decision(
        self,
        fragment_id: str,
        decision: str,
        alternatives: list[str],
        tradeoff: str,
        decision_for: str | None = None,
    ) -> None:
        """Mark a fragment as decision rationale (moves to decision doc).

        Decision content:
        - "We chose X over Y because of tradeoff Z"
        - Explicit discussion of alternatives not taken
        - Reasoning about constraints that led to choice

        Args:
            fragment_id: Fragment to mark
            decision: What decision was made
            alternatives: What alternatives were considered
            tradeoff: What tradeoff drove the decision
            decision_for: ID of spec item this decision justifies
        """
        fragment = self.fragments[fragment_id]
        fragment.decision_for = decision_for
        fragment.record_edit(
            "decision_details",
            {
                "decision": decision,
                "alternatives": alternatives,
                "tradeoff": tradeoff,
                "decision_for": decision_for,
            },
        )
        self.classify_fragment(
            fragment_id,
            FragmentDestination.DECISION,
            f"Decision: {decision}",
            is_tradeoff=True,
            alternatives=alternatives,
        )

    def link_evidence(
        self,
        evidence_id: str,
        spec_id: str,
    ) -> None:
        """Link an evidence fragment to the spec item it proves.

        Args:
            evidence_id: Fragment containing evidence (math, proof)
            spec_id: Fragment containing spec item being proven
        """
        evidence = self.fragments[evidence_id]
        evidence.evidence_for = spec_id
        evidence.record_edit("link_evidence", {"spec_id": spec_id})

    def link_to_invariant(
        self,
        fragment_id: str,
        invariant_id: str,
    ) -> None:
        """Link a fragment to the invariant it satisfies.

        Every spec element should be traceable to an invariant.

        Args:
            fragment_id: Fragment to link
            invariant_id: ID of the invariant this satisfies
        """
        fragment = self.fragments[fragment_id]
        fragment.relates_to_invariant = invariant_id
        fragment.record_edit("link_to_invariant", {"invariant_id": invariant_id})

    def get_leaves(self, file_path: str | None = None) -> list[Fragment]:
        """Get all leaf fragments, optionally filtered by file."""
        leaves = [f for f in self.fragments.values() if f.is_leaf]
        if file_path:
            leaves = [f for f in leaves if f.source_file == file_path]
        return leaves

    def verify_coverage(self, file_path: str) -> tuple[bool, list[Span]]:
        """Verify that leaf fragments cover 100% of the original file.

        Returns:
            (is_complete, gaps) - True if complete, list of uncovered spans if not
        """
        if file_path not in self.original_length:
            raise ValueError(f"Unknown file: {file_path}")

        total_length = self.original_length[file_path]

        # Collect all covered spans from leaves
        covered: list[Span] = []
        for fragment in self.get_leaves(file_path):
            covered.extend(fragment.source_spans)

        # Sort and merge overlapping spans
        covered.sort(key=lambda s: s.start)
        merged: list[Span] = []
        for span in covered:
            if merged and span.start <= merged[-1].end:
                # Overlapping or adjacent - extend
                merged[-1] = Span(merged[-1].start, max(merged[-1].end, span.end))
            else:
                merged.append(span)

        # Find gaps
        gaps: list[Span] = []
        expected_start = 0
        for span in merged:
            if span.start > expected_start:
                gaps.append(Span(expected_start, span.start))
            expected_start = max(expected_start, span.end)

        if expected_start < total_length:
            gaps.append(Span(expected_start, total_length))

        return (len(gaps) == 0, gaps)

    def get_coverage_report(self, file_path: str) -> dict[str, Any]:
        """Generate a coverage report for a file."""
        leaves = self.get_leaves(file_path)
        is_complete, gaps = self.verify_coverage(file_path)

        by_status = {}
        for fragment in leaves:
            status = fragment.status.value
            if status not in by_status:
                by_status[status] = []
            by_status[status].append(fragment.id)

        return {
            "file": file_path,
            "original_length": self.original_length[file_path],
            "leaf_count": len(leaves),
            "complete": is_complete,
            "gaps": [(g.start, g.end) for g in gaps],
            "by_status": by_status,
            "projected_count": len(by_status.get("projected", [])),
            "underspecified_count": len(by_status.get("underspecified", [])),
            "prose_count": len(by_status.get("prose", [])),
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        return {
            "fragments": {
                fid: {
                    "id": f.id,
                    "content": f.content,
                    "status": f.status.value,
                    "source_file": f.source_file,
                    "source_spans": [(s.start, s.end) for s in f.source_spans],
                    "parent_id": f.parent_id,
                    "children_ids": f.children_ids,
                    "projected_form": f.projected_form,
                    "projected_content": f.projected_content,
                    "ambiguities": f.ambiguities,
                    "edits": f.edits,
                    # Annotations for mobility
                    "declarations": f.declarations,
                    "references": f.references,
                    "stuck_on": f.stuck_on,
                    "dependencies_resolved": f.dependencies_resolved,
                    # Order dependencies
                    "comes_after": f.comes_after,
                    "comes_before": f.comes_before,
                    # Composition tracking
                    "composed_into": f.composed_into,
                    # Classification
                    "destination": f.destination.value if f.destination else None,
                    # Relationships (Invariant → Spec → Evidence → Decision)
                    "relates_to_invariant": f.relates_to_invariant,
                    "evidence_for": f.evidence_for,
                    "decision_for": f.decision_for,
                }
                for fid, f in self.fragments.items()
            },
            "original_length": self.original_length,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoverageTracker:
        """Deserialize from storage."""
        tracker = cls()
        tracker.original_length = data["original_length"]

        for fid, fdata in data["fragments"].items():
            fragment = Fragment(
                id=fdata["id"],
                content=fdata["content"],
                status=FragmentStatus(fdata["status"]),
                source_file=fdata["source_file"],
                source_spans=[Span(s[0], s[1]) for s in fdata["source_spans"]],
                parent_id=fdata.get("parent_id"),
                children_ids=fdata.get("children_ids", []),
                projected_form=fdata.get("projected_form"),
                projected_content=fdata.get("projected_content"),
                ambiguities=fdata.get("ambiguities", []),
                edits=fdata.get("edits", []),
                # Annotations for mobility
                declarations=fdata.get("declarations", []),
                references=fdata.get("references", []),
                stuck_on=fdata.get("stuck_on", []),
                dependencies_resolved=fdata.get("dependencies_resolved", []),
                # Order dependencies
                comes_after=fdata.get("comes_after", []),
                comes_before=fdata.get("comes_before", []),
                # Composition tracking
                composed_into=fdata.get("composed_into"),
                # Classification
                destination=FragmentDestination(fdata["destination"])
                if fdata.get("destination")
                else None,
                # Relationships
                relates_to_invariant=fdata.get("relates_to_invariant"),
                evidence_for=fdata.get("evidence_for"),
                decision_for=fdata.get("decision_for"),
            )
            tracker.fragments[fid] = fragment

        return tracker
