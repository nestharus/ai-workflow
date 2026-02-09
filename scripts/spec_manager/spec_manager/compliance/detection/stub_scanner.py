"""Stub scanner for executable gap detection.

Uses ``spec_manager.core.code_analysis.analyze_source()`` for language-agnostic
stub detection.  Each function flagged as a stub by the analyzer is mapped to a
``StubFunction`` record.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from spec_manager.core.code_analysis import analyze_source
from spec_manager.core.gap import GapEvidence


@dataclass
class StubFunction:
    """A function identified as a stub (not implemented)."""

    file_path: str
    line: int
    end_line: int
    name: str
    stub_type: Literal["pass", "ellipsis", "not_implemented"]
    has_docstring: bool
    args: list[str]
    return_annotation: str | None


def _map_stub_reason(reason: str | None) -> Literal["pass", "ellipsis", "not_implemented"]:
    """Map a ``stub_reason`` from code analysis to a stub_type literal.

    The analyzer may return various reason strings depending on the backend
    (LLM or AST test double).  This function normalises them into the three
    canonical categories used by ``StubFunction.stub_type``.
    """
    if reason is None:
        return "pass"
    lower = reason.lower()
    if "ellipsis" in lower or reason == "...":
        return "ellipsis"
    if "notimplemented" in lower.replace(" ", "").replace("_", ""):
        return "not_implemented"
    # "pass", "placeholder", or any other unknown reason
    return "pass"


def scan_stubs(filepath: Path) -> list[StubFunction]:
    """Scan a source file and return all stub functions.

    Uses ``analyze_source()`` from ``spec_manager.core.code_analysis`` to
    perform language-agnostic structural analysis, then filters for functions
    whose ``is_stub`` flag is ``True``.

    Handles both top-level functions and methods within classes.
    Qualified names use ``ClassName.method_name`` format.

    Args:
        filepath: Path to the source file.

    Returns:
        List of StubFunction for each stub found.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    analysis = analyze_source(source, str(filepath))

    stubs: list[StubFunction] = []
    for func in analysis.functions:
        if not func.is_stub:
            continue
        stubs.append(
            StubFunction(
                file_path=str(filepath),
                line=func.start_line,
                end_line=func.end_line,
                name=func.qualified_name,
                stub_type=_map_stub_reason(func.stub_reason),
                has_docstring=func.has_docstring,
                args=list(func.args),
                return_annotation=func.return_annotation,
            )
        )
    return stubs


def stubs_to_gap_evidence(stubs: list[StubFunction]) -> list[GapEvidence]:
    """Convert StubFunction list to GapEvidence for gap synthesis.

    Each StubFunction becomes a GapEvidence with:
        invariant_family = "executable_stub"
        detector = "stub_scanner"
        location = "{file_path}:{line}-{end_line}"
        description = "Stub function: {name} ({stub_type})"
        details = {"stub_type": ..., "args": ..., "return_annotation": ...}

    Args:
        stubs: List of StubFunction from scan_stubs.

    Returns:
        List of GapEvidence objects.
    """
    evidence: list[GapEvidence] = []
    for stub in stubs:
        details: dict[str, Any] = {
            "stub_type": stub.stub_type,
            "args": stub.args,
            "return_annotation": stub.return_annotation,
            "has_docstring": stub.has_docstring,
        }
        evidence.append(
            GapEvidence(
                invariant_family="executable_stub",
                description=f"Stub function: {stub.name} ({stub.stub_type})",
                details=details,
                confidence=1.0,
                location=f"{stub.file_path}:{stub.line}-{stub.end_line}",
                detector="stub_scanner",
            )
        )
    return evidence
