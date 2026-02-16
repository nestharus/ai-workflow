"""Bridge between planning and the existing gap detection system.

Converts pseudocode comments, stub functions, and adjacent details into
Gap objects compatible with the existing gap system.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from spec_manager.comment_planning.models import (
    AdjacentDetail,
    CodeFile,
    CommentKind,
    FunctionInfo,
    PseudocodeComment,
)
from spec_manager.core.code_analysis import analyze_source
from spec_manager.core.gap import Gap, GapEvidence, GapType
from spec_manager.core.gaps import Severity


def scan_for_gaps(code_files: list[CodeFile]) -> list[Gap]:
    """Scan algorithmic code files for unimplemented spec elements.

    Detects:
    1. Pseudocode comments (every PLAN comment = unimplemented spec element)
    2. Stub functions (pass, raise NotImplementedError, Ellipsis)

    Args:
        code_files: List of parsed CodeFile objects.

    Returns:
        List of Gap objects compatible with the existing gap system.
    """
    gaps: list[Gap] = []

    for code_file in code_files:
        # Collect all PLAN comments across all functions and top-level
        plan_comments: list[PseudocodeComment] = []
        for func in code_file.functions:
            plan_comments.extend(c for c in func.comments if c.kind == CommentKind.PLAN)
        plan_comments.extend(c for c in code_file.top_level_comments if c.kind == CommentKind.PLAN)

        # Convert comments to gaps
        gaps.extend(comments_to_gaps(plan_comments))

        # Detect and convert stubs
        stubs: list[FunctionInfo] = []
        unknown_stub_status: list[tuple[FunctionInfo, str]] = []
        for func in code_file.functions:
            is_stub, reason = _is_stub_from_info(func)
            if is_stub is True:
                stubs.append(func)
            elif is_stub is None:
                unknown_stub_status.append((func, reason or "unknown classification failure"))
        gaps.extend(stubs_to_gaps(stubs))
        gaps.extend(stub_classification_unknowns_to_gaps(unknown_stub_status))

    return gaps


def comments_to_gaps(comments: list[PseudocodeComment]) -> list[Gap]:
    """Convert pseudocode comments to Gap objects.

    Each PLAN-kind comment becomes a Gap with:
    - gap_type: GapType.missing_detail
    - severity: Severity.WARNING
    - description: The comment text
    - evidence: file path and line number

    Args:
        comments: List of PseudocodeComment objects.

    Returns:
        List of Gap objects.
    """
    gaps: list[Gap] = []

    for comment in comments:
        if comment.kind != CommentKind.PLAN:
            continue

        gap_id = _generate_gap_id("PLAN", comment.file_path, comment.line_no, comment.text)
        location = f"{comment.file_path}:{comment.line_no}"
        func_ctx = comment.function_name or "top-level"

        evidence = GapEvidence(
            invariant_family="planning",
            description=f"Unimplemented plan comment in {func_ctx}: {comment.text}",
            details={
                "file_path": comment.file_path,
                "line_no": comment.line_no,
                "function_name": comment.function_name,
                "class_name": comment.class_name,
                "comment_kind": comment.kind.value,
                "severity": Severity.WARNING.value,
            },
            confidence=1.0,
            location=location,
            detector="planning.gap_bridge",
        )

        gaps.append(
            Gap(
                id=gap_id,
                gap_type=GapType.missing_detail,
                severity=Severity.WARNING,
                source=[comment.file_path],
                derived_artifact_target=comment.file_path,
                description=comment.text,
                evidence=[evidence],
                status="open",
                created_at=datetime.now().isoformat(),
            )
        )

    return gaps


def stubs_to_gaps(stubs: list[FunctionInfo]) -> list[Gap]:
    """Convert stub functions to Gap objects.

    Each stub becomes a Gap with:
    - gap_type: GapType.missing_detail (used as STUB_FUNCTION equivalent)
    - severity: Severity.ERROR
    - description: Function name and signature

    Args:
        stubs: List of FunctionInfo objects that are stubs.

    Returns:
        List of Gap objects.
    """
    gaps: list[Gap] = []

    for stub in stubs:
        gap_id = _generate_gap_id("STUB", stub.file_path, stub.start_line, stub.name)
        location = f"{stub.file_path}:{stub.start_line}"
        params_str = ", ".join(stub.parameters)
        ret_str = f" -> {stub.return_annotation}" if stub.return_annotation else ""
        signature = f"{stub.name}({params_str}){ret_str}"

        evidence = GapEvidence(
            invariant_family="planning",
            description=f"Stub function: {signature}",
            details={
                "file_path": stub.file_path,
                "start_line": stub.start_line,
                "end_line": stub.end_line,
                "function_name": stub.name,
                "class_name": stub.class_name,
                "parameters": stub.parameters,
                "return_annotation": stub.return_annotation,
                "severity": Severity.ERROR.value,
            },
            confidence=1.0,
            location=location,
            detector="planning.gap_bridge",
        )

        gaps.append(
            Gap(
                id=gap_id,
                gap_type=GapType.missing_detail,
                severity=Severity.ERROR,
                source=[stub.file_path],
                derived_artifact_target=stub.file_path,
                description=f"Stub function: {signature}",
                evidence=[evidence],
                status="open",
                created_at=datetime.now().isoformat(),
            )
        )

    return gaps


def stub_classification_unknowns_to_gaps(
    unknowns: list[tuple[FunctionInfo, str]],
) -> list[Gap]:
    """Convert unknown stub classifications into explicit diagnostic gaps."""
    gaps: list[Gap] = []
    for func, reason in unknowns:
        gap_id = _generate_gap_id("STUB-UNKNOWN", func.file_path, func.start_line, func.name)
        location = f"{func.file_path}:{func.start_line}"
        description = f"Stub status unknown for function {func.name}: {reason}"
        evidence = GapEvidence(
            invariant_family="planning",
            description=description,
            details={
                "file_path": func.file_path,
                "start_line": func.start_line,
                "end_line": func.end_line,
                "function_name": func.name,
                "class_name": func.class_name,
                "reason": reason,
                "severity": Severity.WARNING.value,
            },
            confidence=0.2,
            location=location,
            detector="planning.gap_bridge",
        )
        gaps.append(
            Gap(
                id=gap_id,
                gap_type=GapType.missing_detail,
                severity=Severity.WARNING,
                source=[func.file_path],
                derived_artifact_target=func.file_path,
                description=description,
                evidence=[evidence],
                status="open",
                created_at=datetime.now().isoformat(),
            )
        )
    return gaps


def adjacencies_to_gaps(adjacencies: list[AdjacentDetail]) -> list[Gap]:
    """Convert adjacent details needing plans to Gap objects.

    Each adjacent detail where needs_plan=True becomes a Gap with:
    - gap_type: GapType.missing_detail (used as ADJACENT_DETAIL equivalent)
    - severity: Severity.INFO
    - description: Relationship description

    Args:
        adjacencies: List of AdjacentDetail objects.

    Returns:
        List of Gap objects.
    """
    gaps: list[Gap] = []

    for adj in adjacencies:
        if not adj.needs_plan:
            continue

        gap_id = _generate_gap_id("ADJ", adj.source_function, 0, adj.related_function)
        store_info = f" via {adj.store_or_event}" if adj.store_or_event else ""
        description = (
            f"Adjacent detail: {adj.related_function} "
            f"({adj.relationship}{store_info}) "
            f"needs planning"
        )

        evidence = GapEvidence(
            invariant_family="planning",
            description=description,
            details={
                "source_function": adj.source_function,
                "related_function": adj.related_function,
                "relationship": adj.relationship,
                "store_or_event": adj.store_or_event,
                "has_test_coverage": adj.has_test_coverage,
                "severity": Severity.INFO.value,
            },
            confidence=0.8,
            location=adj.source_function,
            detector="planning.gap_bridge",
        )

        gaps.append(
            Gap(
                id=gap_id,
                gap_type=GapType.missing_detail,
                severity=Severity.INFO,
                source=[adj.source_function],
                derived_artifact_target=adj.related_function,
                description=description,
                evidence=[evidence],
                status="open",
                created_at=datetime.now().isoformat(),
            )
        )

    return gaps


def _generate_gap_id(prefix: str, file_or_func: str, line_no: int, text: str) -> str:
    """Generate a deterministic gap ID from input data.

    Args:
        prefix: Gap type prefix (e.g., "PLAN", "STUB", "ADJ").
        file_or_func: File path or function name.
        line_no: Line number (0 if not applicable).
        text: Description text.

    Returns:
        Gap ID string.
    """
    raw = f"{prefix}:{file_or_func}:{line_no}:{text}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"GAP-{prefix}-{digest}"


def _is_stub_from_info(func: FunctionInfo) -> tuple[bool | None, str | None]:
    """Check if a FunctionInfo represents a stub function.

    Uses language-agnostic LLM-based analysis to determine if a function
    is a stub (has an incomplete implementation).

    Args:
        func: FunctionInfo to check.

    Returns:
        Tuple of (is_stub, reason). ``is_stub`` is None when classification failed.
    """
    if not func.body_lines:
        return False, None

    # Reconstruct source from body_lines and analyze
    source = "\n".join(func.body_lines)
    try:
        analysis = analyze_source(source, func.file_path)
    except Exception as exc:
        return None, f"analysis failed: {type(exc).__name__}: {exc}"

    # The reconstructed source should contain exactly this function;
    # match by name/class to avoid silent first-match selection.
    matches = []
    for raw_func in analysis.functions:
        if raw_func.name != func.name:
            continue
        qualified = str(raw_func.qualified_name or raw_func.name)
        if (
            func.class_name
            and not qualified.endswith(f".{func.class_name}.{func.name}")
            and not qualified.endswith(f".{func.name}")
        ):
            continue
        matches.append(raw_func)

    if not matches:
        return None, "function not found in reconstructed analysis"
    if len(matches) > 1:
        return None, "multiple matching functions in reconstructed analysis"
    return matches[0].is_stub, None
