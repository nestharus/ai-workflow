"""Conftest for core tests.

Injects a local Python AST-based analyzer as a test double so that
no test in this directory makes real LLM calls to the pdd-code-analyzer
agent.  Production code uses ``spec_manager.core.code_analysis``
which calls the LLM; here we replace it with deterministic AST analysis.
"""

from __future__ import annotations

import ast
import io
import tokenize

from spec_manager.core.code_analysis import (
    RawCommentInfo,
    RawFunctionInfo,
    SourceAnalysis,
    clear_cache,
)


# ---------------------------------------------------------------------------
# Test-only helpers (Python AST / tokenize)
# ---------------------------------------------------------------------------


def _is_stub_body_ast(body: list[ast.stmt]) -> tuple[bool, str | None]:
    """Check if a function body is a stub using AST (test-only)."""
    effective = list(body)
    if (
        effective
        and isinstance(effective[0], ast.Expr)
        and isinstance(effective[0].value, ast.Constant)
        and isinstance(effective[0].value.value, str)
    ):
        effective = effective[1:]

    if not effective:
        return True, "placeholder"

    for stmt in effective:
        if isinstance(stmt, ast.Pass):
            continue
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if stmt.value.value is ...:
                continue
            else:
                return False, None
        elif isinstance(stmt, ast.Raise):
            if stmt.exc is not None:
                if isinstance(stmt.exc, ast.Call) and isinstance(stmt.exc.func, ast.Name):
                    if stmt.exc.func.id == "NotImplementedError":
                        continue
                elif isinstance(stmt.exc, ast.Name) and stmt.exc.id == "NotImplementedError":
                    continue
            return False, None
        else:
            return False, None

    if not effective:
        return True, "placeholder"

    first = effective[0]
    if isinstance(first, ast.Pass):
        return True, "placeholder"
    elif (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and first.value.value is ...
    ):
        return True, "ellipsis"
    elif isinstance(first, ast.Raise):
        return True, "not_implemented"
    else:
        return True, "placeholder"


def _extract_decorator_name_ast(decorator: ast.expr) -> str:
    """Extract decorator name from AST (test-only)."""
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Attribute):
        parts: list[str] = []
        node: ast.expr = decorator
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))
    if isinstance(decorator, ast.Call):
        return _extract_decorator_name_ast(decorator.func)
    return ast.dump(decorator)


def _local_python_analyzer(
    content: str, filepath: str, workspace: object
) -> SourceAnalysis:
    """Test double: analyze Python source using AST/tokenize.

    This is ONLY used in tests. Production code uses LLM via code_analysis.
    """
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError:
        return SourceAnalysis()

    # --- Extract functions ---
    functions: list[RawFunctionInfo] = []

    class _FuncVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._stack.append(node.name)
            self.generic_visit(node)
            self._stack.pop()

        def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            qname = ".".join([*self._stack, node.name])
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            is_stub, stub_reason = _is_stub_body_ast(node.body)
            decorators = tuple(_extract_decorator_name_ast(d) for d in node.decorator_list)
            args_list: list[str] = []
            for a in node.args.args:
                args_list.append(a.arg)
            for a in node.args.posonlyargs:
                args_list.append(a.arg)
            for a in node.args.kwonlyargs:
                args_list.append(a.arg)
            if node.args.vararg:
                args_list.append(f"*{node.args.vararg.arg}")
            if node.args.kwarg:
                args_list.append(f"**{node.args.kwarg.arg}")

            docstring = None
            has_ds = False
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                docstring = node.body[0].value.value
                has_ds = True

            ret_ann = None
            if node.returns is not None:
                ret_ann = ast.unparse(node.returns)

            # Compute body_start_line: first line after signature + docstring
            if has_ds and len(node.body) > 1:
                ds_end = node.body[0].end_lineno or node.body[0].lineno
                body_start = ds_end + 1
            elif has_ds:
                ds_end = node.body[0].end_lineno or node.body[0].lineno
                body_start = ds_end + 1
            elif node.body:
                body_start = node.body[0].lineno
            else:
                body_start = node.lineno + 1

            functions.append(
                RawFunctionInfo(
                    name=node.name,
                    qualified_name=qname,
                    start_line=node.lineno,
                    end_line=end,
                    is_async=isinstance(node, ast.AsyncFunctionDef),
                    is_stub=is_stub,
                    stub_reason=stub_reason,
                    has_docstring=has_ds,
                    docstring=docstring,
                    decorators=decorators,
                    args=tuple(args_list),
                    return_annotation=ret_ann,
                    body_start_line=body_start,
                    body_line_count=end - node.lineno,
                )
            )
            self._stack.append(node.name)
            self.generic_visit(node)
            self._stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_func(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_func(node)

    _FuncVisitor().visit(tree)

    # --- Build function line map for comment enclosure lookup ---
    func_map: list[tuple[int, int, str]] = [
        (f.start_line, f.end_line, f.qualified_name) for f in functions
    ]

    def _find_enclosing(line: int) -> str | None:
        best: str | None = None
        best_size = float("inf")
        for s, e, n in func_map:
            if s <= line <= e and (e - s) < best_size:
                best_size = e - s
                best = n
        return best

    # --- Extract comments ---
    comments: list[RawCommentInfo] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(content).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                raw = tok.string
                text = raw.lstrip("#").strip()
                comments.append(
                    RawCommentInfo(
                        line=tok.start[0],
                        col_offset=tok.start[1],
                        text=text,
                        raw=raw,
                        enclosing_function=_find_enclosing(tok.start[0]),
                    )
                )
    except tokenize.TokenError:
        pass

    return SourceAnalysis(functions=functions, comments=comments)


# NOTE: The autouse _use_local_analyzer fixture is in the ROOT conftest
# (tests/conftest.py) so ALL tests get the test double, not just core tests.
# The _local_python_analyzer function defined above is imported by root conftest.
