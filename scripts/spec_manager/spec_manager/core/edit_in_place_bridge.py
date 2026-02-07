"""Bridge between the edit-in-place engine and the existing refinement workflow.

Provides adapter functions that convert edit-in-place analysis output
(``FileTranslationState``, ``FunctionInfo``, ``SpecComment``) into the
existing refinement data structures (``Gap``, ``TrackedUnit``, ``GapQueue``),
enabling gradual adoption of the edit-in-place engine without replacing
the existing refinement pipeline.
"""

from __future__ import annotations

from datetime import datetime

from spec_manager.core.edit_in_place import (
    CommentKind,
    FileTranslationState,
    FunctionInfo,
    ProjectTranslationState,
    SpecComment,
    TranslationState,
)
from spec_manager.core.gaps import Severity
from spec_manager.core.provenance import (
    SourceLocation,
    TrackedUnit,
    UnitStatus,
    UnitType,
)
from spec_manager.refinement.core.gap import Gap, GapEvidence, GapType
from spec_manager.refinement.core.gap_queue import GapQueue


def spec_comment_to_gap(comment: SpecComment) -> Gap:
    """Convert a SpecComment into a refinement Gap.

    Maps:
    - ``SpecComment.kind SPEC`` -> ``GapType.missing_detail``
    - ``SpecComment.kind TODO`` -> ``GapType.ambiguity``
    - Evidence is the comment text + location
    - Source is ``file:line``
    - Severity is always ``'error'`` (spec comments = must-resolve)

    Args:
        comment: A classified spec comment from the edit-in-place engine.

    Returns:
        A refinement ``Gap`` object compatible with the existing workflow.
    """
    # Map comment kind to gap type
    if comment.kind == CommentKind.TODO:
        gap_type = GapType.ambiguity
    else:
        gap_type = GapType.missing_detail

    # Build evidence
    evidence = GapEvidence(
        invariant_family="edit_in_place",
        description=comment.text,
        details={
            "raw": comment.raw,
            "kind": comment.kind.value,
            "enclosing_function": comment.enclosing_function,
        },
        confidence=1.0,
        location=f"{comment.file}:{comment.line}",
        detector="edit_in_place_scanner",
    )

    # Build source reference
    source_ref = f"{comment.file}:{comment.line}"

    # Determine derived artifact target
    target = comment.enclosing_function or "module-level"

    return Gap(
        id=f"EIP-{comment.file}:{comment.line}:{comment.col_offset}",
        gap_type=gap_type,
        severity=Severity.ERROR,
        source=[source_ref],
        derived_artifact_target=target,
        description=comment.text,
        evidence=[evidence],
        status="open",
        created_at=datetime.now().isoformat(),
    )


def function_info_to_tracked_unit(func: FunctionInfo) -> TrackedUnit:
    """Convert a FunctionInfo into a TrackedUnit for provenance tracking.

    Maps:
    - ``FunctionInfo`` -> ``TrackedUnit`` with ``UnitType.ALGORITHM``
    - ``SourceLocation`` from function's file + line range
    - Status based on translation state:
        ``UNRESOLVED/STUB`` -> ``UnitStatus.PENDING``
        ``PARTIAL`` -> ``UnitStatus.PENDING``
        ``IMPLEMENTED`` -> ``UnitStatus.PROCESSED``
        ``VERIFIED`` -> ``UnitStatus.MAPPED``

    Args:
        func: A parsed function info from the edit-in-place engine.

    Returns:
        A ``TrackedUnit`` compatible with ``ProvenanceTracker``.
    """
    # Map translation state to unit status
    status_map = {
        TranslationState.UNRESOLVED: UnitStatus.PENDING,
        TranslationState.STUB: UnitStatus.PENDING,
        TranslationState.PARTIAL: UnitStatus.PENDING,
        TranslationState.IMPLEMENTED: UnitStatus.PROCESSED,
        TranslationState.VERIFIED: UnitStatus.MAPPED,
    }
    status = status_map.get(func.translation_state, UnitStatus.PENDING)

    # Build content from docstring or function signature
    content = func.docstring or f"def {func.qualified_name}({', '.join(func.args)})"

    source = SourceLocation(
        file=func.file,
        line_start=func.line_start,
        line_end=func.line_end,
    )

    return TrackedUnit(
        id=f"EIP-FUNC-{func.qualified_name}",
        content=content,
        unit_type=UnitType.ALGORITHM,
        source=source,
        introduced_by="edit_in_place",
        status=status,
        metadata={
            "translation_state": func.translation_state.value,
            "is_async": func.is_async,
            "stub_reason": func.stub_reason,
            "decorators": func.decorators,
        },
    )


def file_state_to_gap_queue(state: FileTranslationState) -> GapQueue:
    """Convert a FileTranslationState into a GapQueue for the existing workflow.

    Creates a Gap for each spec comment and each stub function,
    wraps them in a GapQueue with stagnation tracking.

    Args:
        state: A file translation state from the edit-in-place engine.

    Returns:
        A ``GapQueue`` with gaps derived from spec comments and stub functions.
    """
    gaps: list[Gap] = []

    # Convert spec comments to gaps
    for comment in state.gaps:
        gaps.append(spec_comment_to_gap(comment))

    # Convert stub functions to gaps (stubs without spec comments are still gaps)
    for func in state.functions:
        if func.translation_state == TranslationState.STUB:
            evidence = GapEvidence(
                invariant_family="edit_in_place",
                description=f"Stub function: {func.qualified_name} ({func.stub_reason})",
                details={
                    "stub_reason": func.stub_reason,
                    "qualified_name": func.qualified_name,
                },
                confidence=1.0,
                location=f"{func.file}:{func.line_start}",
                detector="edit_in_place_stub_detector",
            )
            gap = Gap(
                id=f"EIP-STUB-{func.qualified_name}",
                gap_type=GapType.missing_detail,
                severity=Severity.ERROR,
                source=[f"{func.file}:{func.line_start}-{func.line_end}"],
                derived_artifact_target=func.qualified_name,
                description=f"Stub function needs implementation: {func.qualified_name}",
                evidence=[evidence],
                status="open",
                created_at=datetime.now().isoformat(),
            )
            gaps.append(gap)

    queue = GapQueue(gaps=gaps)
    return queue


def project_state_to_gap_queue(state: ProjectTranslationState) -> GapQueue:
    """Convert ProjectTranslationState to a single GapQueue.

    Aggregates gaps from all files into a single queue.

    Args:
        state: A project translation state from the edit-in-place engine.

    Returns:
        A ``GapQueue`` aggregating gaps from all analyzed files.
    """
    all_gaps: list[Gap] = []
    for file_state in state.files.values():
        file_queue = file_state_to_gap_queue(file_state)
        all_gaps.extend(file_queue.gaps)

    return GapQueue(gaps=all_gaps)
