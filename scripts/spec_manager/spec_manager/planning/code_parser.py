"""Python-specific code parser using ast + tokenize.

Parses Python files to extract function structures, comments, insertion
points, and stub detection. Combines ast (for structure) with tokenize
(for comments, since ast strips them).
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

from spec_manager.planning.models import (
    CodeFile,
    CommentKind,
    FunctionInfo,
    InsertionPoint,
    PseudocodeComment,
)

# Verbs that indicate a PLAN-kind comment (intent to do something)
_PLAN_VERBS = frozenset(
    {
        "validate",
        "check",
        "apply",
        "send",
        "compute",
        "calculate",
        "build",
        "create",
        "update",
        "delete",
        "remove",
        "insert",
        "fetch",
        "load",
        "save",
        "store",
        "process",
        "transform",
        "convert",
        "parse",
        "extract",
        "filter",
        "merge",
        "sort",
        "iterate",
        "loop",
        "return",
        "raise",
        "emit",
        "dispatch",
        "invoke",
        "call",
        "initialize",
        "configure",
        "register",
        "normalize",
        "aggregate",
        "map",
        "reduce",
        "resolve",
        "determine",
        "ensure",
        "verify",
        "handle",
        "retry",
        "propagate",
        "collect",
        "accumulate",
        "generate",
        "render",
        "format",
        "serialize",
        "deserialize",
        "encode",
        "decode",
        "encrypt",
        "decrypt",
        "compress",
        "decompress",
        "schedule",
        "execute",
        "run",
        "start",
        "stop",
        "reset",
        "flush",
        "sync",
        "wait",
        "poll",
        "listen",
        "subscribe",
        "publish",
        "notify",
        "log",
        "track",
        "measure",
        "allocate",
        "release",
        "open",
        "close",
        "read",
        "write",
        "set",
        "get",
    }
)

# Reverse-translation markers
_REVERSE_MARKERS = frozenset(
    {
        "[reverse-translated]",
        "reverse-translated:",
        "reverse translated:",
        "[reversed]",
    }
)


def _classify_comment(text: str) -> CommentKind:
    """Classify a comment as PLAN, REVERSE, or ANNOTATION.

    Args:
        text: The comment text (stripped of '# ' prefix).

    Returns:
        CommentKind classification.
    """
    lower = text.lower().strip()

    # Check for reverse-translation markers
    for marker in _REVERSE_MARKERS:
        if marker in lower:
            return CommentKind.REVERSE

    # Check for plan verbs at word boundaries
    words = lower.split()
    if words:
        first_word = words[0].rstrip(":")
        if first_word in _PLAN_VERBS:
            return CommentKind.PLAN

    # Check for verbs anywhere in the comment (with weaker signal)
    for word in words:
        clean = word.strip("(),.:;!?")
        if clean in _PLAN_VERBS:
            return CommentKind.PLAN

    return CommentKind.ANNOTATION


def _extract_comments_from_source(source: str, file_path: str) -> list[PseudocodeComment]:
    """Extract all comments from Python source using tokenize.

    Args:
        source: Python source code string.
        file_path: Path for attribution.

    Returns:
        List of PseudocodeComment objects.
    """
    comments: list[PseudocodeComment] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return comments

    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            line_no = tok.start[0]
            col = tok.start[1]
            raw = tok.string
            # Strip the '# ' or '#' prefix
            if raw.startswith("# "):
                text = raw[2:]
            elif raw.startswith("#"):
                text = raw[1:]
            else:
                text = raw

            kind = _classify_comment(text)
            comments.append(
                PseudocodeComment(
                    file_path=file_path,
                    line_no=line_no,
                    text=text.strip(),
                    kind=kind,
                    indent_level=col,
                    function_name=None,  # Filled in later by parse_file
                    class_name=None,  # Filled in later by parse_file
                )
            )

    return comments


def _extract_function_calls_from_ast(node: ast.AST) -> list[str]:
    """Extract function call names from an AST node using ast.walk.

    Args:
        node: AST node to walk.

    Returns:
        List of function names called (may include duplicates).
    """
    calls: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.append(child.func.attr)
    return calls


def _get_function_end_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Get the last line number of a function definition.

    Args:
        node: The function AST node.

    Returns:
        1-based end line number (inclusive).
    """
    return node.end_lineno or node.lineno


def _get_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Extract docstring from a function node.

    Args:
        node: The function AST node.

    Returns:
        Docstring string or None.
    """
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ):
        return node.body[0].value.value
    return None


def _get_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract parameter names from a function definition.

    Args:
        node: The function AST node.

    Returns:
        List of parameter name strings.
    """
    params: list[str] = []
    for arg in node.args.args:
        params.append(arg.arg)
    for arg in node.args.posonlyargs:
        params.append(arg.arg)
    for arg in node.args.kwonlyargs:
        params.append(arg.arg)
    if node.args.vararg:
        params.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        params.append(f"**{node.args.kwarg.arg}")
    return params


def _get_return_annotation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Extract return annotation as a string.

    Args:
        node: The function AST node.

    Returns:
        Return annotation string or None.
    """
    if node.returns is None:
        return None
    return ast.unparse(node.returns)


def _get_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract decorator names from a function definition.

    Args:
        node: The function AST node.

    Returns:
        List of decorator name strings.
    """
    decorators: list[str] = []
    for dec in node.decorator_list:
        decorators.append(ast.unparse(dec))
    return decorators


def _assign_comments_to_functions(
    comments: list[PseudocodeComment],
    functions: list[FunctionInfo],
) -> tuple[list[PseudocodeComment], list[PseudocodeComment]]:
    """Assign comments to their enclosing functions.

    Returns:
        Tuple of (function_comments, top_level_comments).
        Function comments have their function_name and class_name filled in.
    """
    assigned: list[PseudocodeComment] = []
    top_level: list[PseudocodeComment] = []

    for comment in comments:
        found = False
        for func in functions:
            if func.start_line <= comment.line_no <= func.end_line:
                # Re-create with function context (frozen dataclass)
                assigned.append(
                    PseudocodeComment(
                        file_path=comment.file_path,
                        line_no=comment.line_no,
                        text=comment.text,
                        kind=comment.kind,
                        indent_level=comment.indent_level,
                        function_name=func.name,
                        class_name=func.class_name,
                    )
                )
                found = True
                break
        if not found:
            top_level.append(comment)

    return assigned, top_level


def parse_file(file_path: str) -> CodeFile:
    """Parse a Python file into a CodeFile structure using ast + tokenize.

    Args:
        file_path: Absolute path to the Python file.

    Returns:
        CodeFile with functions, comments, imports, and classes.

    Raises:
        FileNotFoundError: If the file does not exist.
        SyntaxError: If the file contains invalid Python.
    """
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")
    return parse_source(source, file_path)


def parse_source(source: str, file_path: str) -> CodeFile:
    """Parse Python source code into a CodeFile structure.

    Args:
        source: Python source code string.
        file_path: Path for attribution in results.

    Returns:
        CodeFile with functions, comments, imports, and classes.

    Raises:
        SyntaxError: If the source contains invalid Python.
    """
    tree = ast.parse(source, filename=file_path)
    lines = source.splitlines()

    # Extract imports
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(f"{module}.{alias.name}")

    # Extract classes
    classes: list[str] = []
    class_ranges: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)
            end_line = node.end_lineno or node.lineno
            class_ranges.append((node.name, node.lineno, end_line))

    # Extract all comments
    all_comments = _extract_comments_from_source(source, file_path)

    # Extract functions (including methods within classes)
    functions: list[FunctionInfo] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start_line = node.lineno
            end_line = _get_function_end_line(node)
            indent = node.col_offset
            params = _get_parameters(node)
            ret_ann = _get_return_annotation(node)
            docstring = _get_docstring(node)
            decorators = _get_decorators(node)
            calls = _extract_function_calls_from_ast(node)

            # Get body lines
            body_lines = lines[start_line - 1 : end_line]

            # Determine enclosing class
            class_name: str | None = None
            for cname, cstart, cend in class_ranges:
                if cstart <= start_line and end_line <= cend:
                    class_name = cname
                    break

            func_info = FunctionInfo(
                name=node.name,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                indent_level=indent,
                parameters=params,
                return_annotation=ret_ann,
                docstring=docstring,
                body_lines=body_lines,
                calls=calls,
                comments=[],  # Filled in below
                class_name=class_name,
                decorators=decorators,
            )
            functions.append(func_info)

    # Assign comments to functions
    assigned_comments, top_level_comments = _assign_comments_to_functions(
        all_comments, functions
    )

    # Group assigned comments by function and rebuild FunctionInfo with comments
    comments_by_func: dict[str, list[PseudocodeComment]] = {}
    for comment in assigned_comments:
        key = f"{comment.class_name or ''}.{comment.function_name}"
        comments_by_func.setdefault(key, []).append(comment)

    enriched_functions: list[FunctionInfo] = []
    for func in functions:
        key = f"{func.class_name or ''}.{func.name}"
        func_comments = comments_by_func.get(key, [])
        # Rebuild with comments (frozen dataclass workaround via FunctionInfo)
        enriched_functions.append(
            FunctionInfo(
                name=func.name,
                file_path=func.file_path,
                start_line=func.start_line,
                end_line=func.end_line,
                indent_level=func.indent_level,
                parameters=func.parameters,
                return_annotation=func.return_annotation,
                docstring=func.docstring,
                body_lines=func.body_lines,
                calls=func.calls,
                comments=func_comments,
                class_name=func.class_name,
                decorators=func.decorators,
            )
        )

    return CodeFile(
        file_path=file_path,
        functions=enriched_functions,
        top_level_comments=top_level_comments,
        imports=imports,
        classes=classes,
    )


def find_insertion_points(code_file: CodeFile, function_name: str) -> list[InsertionPoint]:
    """Find valid insertion points within a function.

    Insertion points are between statements, respecting control flow.
    Each point knows its context (what comes before/after).

    Args:
        code_file: Parsed code file.
        function_name: Name of the target function.

    Returns:
        List of InsertionPoint objects.

    Raises:
        ValueError: If function_name is not found in the code file.
    """
    func = _find_function(code_file, function_name)
    if func is None:
        raise ValueError(
            f"Function '{function_name}' not found in {code_file.file_path}"
        )

    source = Path(code_file.file_path).read_text(encoding="utf-8")
    return _find_insertion_points_from_source(source, func, code_file.file_path)


def _find_insertion_points_from_source(
    source: str,
    func: FunctionInfo,
    file_path: str,
) -> list[InsertionPoint]:
    """Find insertion points within a function from source text.

    Args:
        source: Full file source.
        func: Function info.
        file_path: File path for attribution.

    Returns:
        List of InsertionPoint objects.
    """
    lines = source.splitlines()
    points: list[InsertionPoint] = []

    # Parse to get AST statements within the function
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return points

    # Find the function node
    func_node = _find_func_node(tree, func.name)
    if func_node is None:
        return points

    body_indent = func.indent_level + 4  # Standard Python indentation

    # Skip docstring if present
    body = func_node.body
    first_stmt_idx = 0
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        first_stmt_idx = 1

    # Add insertion point at the start of function body (after docstring)
    if body:
        if first_stmt_idx < len(body):
            first_stmt = body[first_stmt_idx]
            first_line = first_stmt.lineno
        else:
            first_line = func.end_line

        # Find the line after the docstring or def statement
        insert_after = (body[first_stmt_idx - 1].end_lineno if first_stmt_idx > 0 else func_node.lineno)
        preceding = lines[insert_after - 1] if insert_after <= len(lines) else ""
        following = lines[first_line - 1] if first_line <= len(lines) and first_stmt_idx < len(body) else ""

        points.append(
            InsertionPoint(
                file_path=file_path,
                line_no=insert_after,
                indent_level=body_indent,
                function_name=func.name,
                preceding_code=preceding.strip(),
                following_code=following.strip(),
                rationale="Start of function body",
            )
        )

    # Add insertion points between statements
    for i in range(first_stmt_idx, len(body) - 1):
        current_stmt = body[i]
        next_stmt = body[i + 1]

        current_end = current_stmt.end_lineno or current_stmt.lineno
        next_start = next_stmt.lineno

        preceding = lines[current_end - 1] if current_end <= len(lines) else ""
        following = lines[next_start - 1] if next_start <= len(lines) else ""

        rationale = f"Between {type(current_stmt).__name__} and {type(next_stmt).__name__}"

        points.append(
            InsertionPoint(
                file_path=file_path,
                line_no=current_end,
                indent_level=body_indent,
                function_name=func.name,
                preceding_code=preceding.strip(),
                following_code=following.strip(),
                rationale=rationale,
            )
        )

    # Add insertion point at the end of the function body
    if body:
        last_stmt = body[-1]
        last_end = last_stmt.end_lineno or last_stmt.lineno
        preceding = lines[last_end - 1] if last_end <= len(lines) else ""

        points.append(
            InsertionPoint(
                file_path=file_path,
                line_no=last_end,
                indent_level=body_indent,
                function_name=func.name,
                preceding_code=preceding.strip(),
                following_code="",
                rationale="End of function body",
            )
        )

    return points


def _find_func_node(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find a function node by name in an AST.

    Args:
        tree: Parsed AST module.
        name: Function name to find.

    Returns:
        The function node, or None if not found.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    return None


def _find_function(code_file: CodeFile, function_name: str) -> FunctionInfo | None:
    """Find a function by name in a CodeFile.

    Args:
        code_file: Parsed code file.
        function_name: Name of the function to find.

    Returns:
        FunctionInfo or None if not found.
    """
    for func in code_file.functions:
        if func.name == function_name:
            return func
    return None


def extract_comments(file_path: str) -> list[PseudocodeComment]:
    """Extract all pseudocode comments from a file using tokenize.

    Uses tokenize.generate_tokens to find COMMENT tokens.
    Classifies each as PLAN, REVERSE, or ANNOTATION based on heuristics.

    Args:
        file_path: Absolute path to the Python file.

    Returns:
        List of PseudocodeComment objects.
    """
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")
    return _extract_comments_from_source(source, file_path)


def extract_function_calls(function: FunctionInfo) -> list[str]:
    """Extract all function calls within a function body using ast.walk.

    This re-parses the function body lines to extract call information.

    Args:
        function: FunctionInfo to analyze.

    Returns:
        List of function names called (deduplicated).
    """
    # The calls are already extracted during parsing
    return list(dict.fromkeys(function.calls))


def detect_stubs(code_file: CodeFile) -> list[FunctionInfo]:
    """Find stub functions (pass, raise NotImplementedError, Ellipsis body).

    Args:
        code_file: Parsed code file.

    Returns:
        List of FunctionInfo objects that are stubs.
    """
    stubs: list[FunctionInfo] = []
    source = Path(code_file.file_path).read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=code_file.file_path)
    except SyntaxError:
        return stubs

    stub_func_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_stub_function(node):
                stub_func_names.add(node.name)

    for func in code_file.functions:
        if func.name in stub_func_names:
            stubs.append(func)

    return stubs


def _is_stub_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if a function is a stub.

    A stub has a body consisting only of:
    - pass statement
    - Ellipsis (...)
    - raise NotImplementedError
    - A docstring followed by pass/Ellipsis/raise NotImplementedError

    Args:
        node: Function AST node.

    Returns:
        True if the function is a stub.
    """
    body = node.body

    # Skip docstring
    effective_body = body
    if (
        len(body) >= 1
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        effective_body = body[1:]

    if not effective_body:
        return True  # Just a docstring

    if len(effective_body) != 1:
        return False

    stmt = effective_body[0]

    # pass
    if isinstance(stmt, ast.Pass):
        return True

    # Ellipsis (...)
    if (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is ...
    ):
        return True

    # raise NotImplementedError
    if isinstance(stmt, ast.Raise) and stmt.exc is not None:
        if isinstance(stmt.exc, ast.Call) and isinstance(stmt.exc.func, ast.Name):
            if stmt.exc.func.id == "NotImplementedError":
                return True
        elif isinstance(stmt.exc, ast.Name) and stmt.exc.id == "NotImplementedError":
            return True

    return False


def detect_stubs_from_source(source: str, file_path: str) -> list[FunctionInfo]:
    """Find stub functions from source code string.

    Args:
        source: Python source code.
        file_path: Path for attribution.

    Returns:
        List of FunctionInfo objects that are stubs.
    """
    code_file = parse_source(source, file_path)
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []

    stub_func_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_stub_function(node):
                stub_func_names.add(node.name)

    return [func for func in code_file.functions if func.name in stub_func_names]
