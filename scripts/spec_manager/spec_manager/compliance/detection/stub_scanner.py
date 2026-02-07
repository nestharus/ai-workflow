"""Stub scanner for executable gap detection.

AST-parses Python files to find functions whose bodies are only `pass`,
`raise NotImplementedError(...)`, or `Ellipsis (...)`, optionally preceded
by a docstring.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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


def _get_return_annotation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Extract return annotation as a string if present."""
    if node.returns is None:
        return None
    try:
        return ast.unparse(node.returns)
    except Exception:
        return None


def _get_arg_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract parameter names from a function definition."""
    names: list[str] = []
    for arg in node.args.args:
        names.append(arg.arg)
    for arg in node.args.posonlyargs:
        names.append(arg.arg)
    for arg in node.args.kwonlyargs:
        names.append(arg.arg)
    if node.args.vararg:
        names.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        names.append(f"**{node.args.kwarg.arg}")
    return names


def _is_docstring(stmt: ast.stmt) -> bool:
    """Check if a statement is a docstring (Expr containing a string constant)."""
    if not isinstance(stmt, ast.Expr):
        return False
    if not isinstance(stmt.value, ast.Constant):
        return False
    return isinstance(stmt.value.value, str)


def _is_pass(stmt: ast.stmt) -> bool:
    """Check if a statement is a `pass` statement."""
    return isinstance(stmt, ast.Pass)


def _is_ellipsis(stmt: ast.stmt) -> bool:
    """Check if a statement is an Ellipsis expression (`...`)."""
    if not isinstance(stmt, ast.Expr):
        return False
    return isinstance(stmt.value, ast.Constant) and stmt.value.value is ...


def _is_not_implemented_raise(stmt: ast.stmt) -> bool:
    """Check if a statement is `raise NotImplementedError(...)`."""
    if not isinstance(stmt, ast.Raise):
        return False
    exc = stmt.exc
    if exc is None:
        return False
    # raise NotImplementedError(...)
    if isinstance(exc, ast.Call):
        func = exc.func
        if isinstance(func, ast.Name) and func.id == "NotImplementedError":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "NotImplementedError":
            return True
    # raise NotImplementedError
    return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"


def _classify_stub(
    body: list[ast.stmt],
) -> tuple[Literal["pass", "ellipsis", "not_implemented"] | None, bool]:
    """Classify a function body as a stub or not.

    Returns (stub_type, has_docstring) or (None, False) if not a stub.
    A function is a stub if its body consists of ONLY:
    1. An optional docstring (Expr(Constant(str)))
    2. Followed by one of:
       a. `pass` statement
       b. `raise NotImplementedError(...)`
       c. Ellipsis expression (`...`)
    """
    if not body:
        return None, False

    stmts = list(body)
    has_docstring = False

    if stmts and _is_docstring(stmts[0]):
        has_docstring = True
        stmts = stmts[1:]

    if not stmts:
        return None, has_docstring

    if len(stmts) != 1:
        return None, has_docstring

    stmt = stmts[0]

    if _is_pass(stmt):
        return "pass", has_docstring
    if _is_ellipsis(stmt):
        return "ellipsis", has_docstring
    if _is_not_implemented_raise(stmt):
        return "not_implemented", has_docstring

    return None, has_docstring


def scan_stubs(filepath: Path) -> list[StubFunction]:
    """AST-parse a Python file and return all stub functions.

    A function is a stub if its body consists of ONLY:
    1. An optional docstring (Expr(Constant(str)))
    2. Followed by one of:
       a. `pass` statement
       b. `raise NotImplementedError(...)`
       c. Ellipsis expression (`...`)

    Handles both top-level functions and methods within classes.
    Qualified names use "ClassName.method_name" format.

    Args:
        filepath: Path to the Python file.

    Returns:
        List of StubFunction for each stub found.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    stubs: list[StubFunction] = []

    def _visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                class_prefix = f"{child.name}." if not prefix else f"{prefix}{child.name}."
                _visit(child, class_prefix)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{prefix}{child.name}"
                stub_type, has_docstring = _classify_stub(child.body)
                if stub_type is not None:
                    stubs.append(
                        StubFunction(
                            file_path=str(filepath),
                            line=child.lineno,
                            end_line=child.end_lineno or child.lineno,
                            name=qualified,
                            stub_type=stub_type,
                            has_docstring=has_docstring,
                            args=_get_arg_names(child),
                            return_annotation=_get_return_annotation(child),
                        )
                    )
                # Visit nested functions/classes within this function
                _visit(child, f"{qualified}.")

    _visit(tree, "")
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
