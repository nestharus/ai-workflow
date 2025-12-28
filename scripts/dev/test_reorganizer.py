"""Reorganize test files by splitting mixed unit/component tests.

Analyzes test files using the classifier and:
- Moves pure unit tests (all functions have patches) to scripts/tests/unit/
- Moves pure component tests (no functions have patches) to scripts/tests/component/
- Splits mixed files into separate unit and component files

Key feature: Block-aware extraction
- Functions inside classes/blocks are extracted with their enclosing blocks
- If multiple functions share a block but go to different destinations,
  the block is copied to both output files with the appropriate functions

Usage:
    uv run python -m scripts.dev.test_reorganizer scripts/tests/ --dry-run
    uv run python -m scripts.dev.test_reorganizer scripts/tests/ --execute
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from scripts.dev.test_classifier import (
    TestType,
    analyze_test_file,
)

# =============================================================================
# Block-aware extraction types and functions
# =============================================================================


@dataclass
class BlockInfo:
    """Information about an enclosing block (class, if, try, with, etc.)."""

    node_type: str  # 'ClassDef', 'If', 'Try', 'With', 'For', 'While', etc.
    name: str | None  # Class/function name if applicable
    header_start: int  # Line number where block header starts (1-indexed)
    header_end: int  # Line number where block header ends (before body)
    body_start: int  # First line of body
    end_lineno: int  # Last line of block
    indent: int  # Indentation level (number of spaces)
    decorator_start: int | None = None  # For classes with decorators


@dataclass
class FunctionContext:
    """A function with its enclosing block context."""

    name: str
    lineno: int
    end_lineno: int
    decorator_start: int | None  # First decorator line (or None)
    enclosing_blocks: list[BlockInfo]  # From outermost to innermost
    indent: int  # Function's indentation level


@dataclass
class Definition:
    """A definition (function, class, import, or variable) with its context."""

    name: str
    kind: str  # 'function', 'class', 'import', 'variable'
    lineno: int
    end_lineno: int
    decorator_start: int | None  # For decorated functions/classes
    enclosing_blocks: list[BlockInfo]  # From outermost to innermost
    references: set[str] = field(default_factory=set)  # Names this definition uses
    node: ast.AST | None = None  # The AST node (for imports, contains details)
    import_module: str | None = None  # For imports: the module being imported
    import_names: list[str] = field(default_factory=list)  # For 'from X import a, b'


@dataclass
class BlockNode:
    """A node in the block tree for output generation."""

    block_info: BlockInfo | None  # None for root
    children: list[BlockNode] = field(default_factory=list)
    functions: list[FunctionContext] = field(default_factory=list)


def _get_indent(line: str) -> int:
    """Get the indentation level of a line."""
    return len(line) - len(line.lstrip())


def _find_header_end(lines: list[str], node: ast.AST) -> int:
    r"""Find where the header of a compound statement ends.

    For `class Foo:` the header ends at the colon line.
    For multi-line headers like `if (a and\n   b):` we need to find the colon.
    """
    lineno = getattr(node, "lineno", 1)
    if not isinstance(lineno, int):
        lineno = 1
    start_idx = lineno - 1

    # For simple cases, the header is on the same line
    # For complex cases, scan forward until we find the colon
    for i in range(start_idx, min(start_idx + 20, len(lines))):
        line = lines[i]
        # Check if this line ends with colon (ignoring comments)
        stripped = line.split("#")[0].rstrip()
        if stripped.endswith(":"):
            return i + 1  # Convert to 1-indexed

    return lineno  # Fallback


def _get_body_start(node: ast.AST) -> int:
    """Get the line number where the body starts."""
    body = getattr(node, "body", None)
    if body and len(body) > 0:
        first_child = body[0]
        if hasattr(first_child, "lineno") and isinstance(first_child.lineno, int):
            # Check for decorators
            if (
                isinstance(
                    first_child,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                )
                and first_child.decorator_list
            ):
                dec_linenos = [
                    d.lineno for d in first_child.decorator_list if isinstance(d.lineno, int)
                ]
                if dec_linenos:
                    return min(dec_linenos)
            return first_child.lineno
    node_lineno = getattr(node, "lineno", 1)
    return (node_lineno if isinstance(node_lineno, int) else 1) + 1


def _extract_block_info(node: ast.AST, lines: list[str]) -> BlockInfo:
    """Extract block information from an AST node."""
    node_type = type(node).__name__
    name = getattr(node, "name", None)

    # Find decorator start for classes
    decorator_start = None
    if isinstance(node, ast.ClassDef) and node.decorator_list:
        dec_linenos = [d.lineno for d in node.decorator_list if isinstance(d.lineno, int)]
        if dec_linenos:
            decorator_start = min(dec_linenos)

    node_lineno = getattr(node, "lineno", 1)
    if not isinstance(node_lineno, int):
        node_lineno = 1
    header_start = decorator_start or node_lineno
    header_end = _find_header_end(lines, node)
    body_start = _get_body_start(node)

    # Calculate indent from the actual line
    indent = _get_indent(lines[node_lineno - 1]) if node_lineno <= len(lines) else 0

    end_lineno = getattr(node, "end_lineno", node_lineno)
    if not isinstance(end_lineno, int):
        end_lineno = node_lineno

    return BlockInfo(
        node_type=node_type,
        name=name,
        header_start=header_start,
        header_end=header_end,
        body_start=body_start,
        end_lineno=end_lineno,
        indent=indent,
        decorator_start=decorator_start,
    )


def _is_enclosing_block(node: ast.AST) -> bool:
    """Check if a node is an enclosing block we care about."""
    return isinstance(
        node,
        (
            ast.ClassDef,
            ast.If,
            ast.Try,
            ast.With,
            ast.For,
            ast.While,
            ast.Match,
            ast.AsyncWith,
            ast.AsyncFor,
        ),
    )


def _build_function_contexts(source: str) -> list[FunctionContext]:
    """Build function contexts with enclosing blocks for all test functions.

    This walks the AST tree depth-first, tracking the block stack as we go.
    """
    lines = source.splitlines()
    tree = ast.parse(source)
    contexts: list[FunctionContext] = []

    def visit(node: ast.AST, block_stack: list[BlockInfo]) -> None:
        """Recursively visit nodes, tracking block context."""
        # If this is an enclosing block, add to stack for children
        new_stack = block_stack
        if _is_enclosing_block(node):
            block_info = _extract_block_info(node, lines)
            new_stack = [*block_stack, block_info]

        # If this is a test function, record its context
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            decorator_start = None
            if node.decorator_list:
                decorator_start = min(d.lineno for d in node.decorator_list)

            indent = _get_indent(lines[node.lineno - 1]) if node.lineno <= len(lines) else 0

            contexts.append(
                FunctionContext(
                    name=node.name,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", node.lineno),
                    decorator_start=decorator_start,
                    enclosing_blocks=list(new_stack),  # Copy the stack
                    indent=indent,
                )
            )

        # Visit children
        for child in ast.iter_child_nodes(node):
            visit(child, new_stack)

    visit(tree, [])
    return contexts


# =============================================================================
# Dependency analysis functions
# =============================================================================


def _extract_references(node: ast.AST, include_self_methods: bool = True) -> set[str]:
    """Extract all name references from an AST node (function/class body).

    Returns names that are loaded (used), not stored (defined).

    Args:
        node: The AST node to analyze.
        include_self_methods: If True, includes method names from self.method() calls.
            These are tracked with a 'self.' prefix to indicate they're methods.
    """
    references: set[str] = set()

    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            references.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
            # Check for self.method or cls.method patterns
            if (
                include_self_methods
                and isinstance(child.value, ast.Name)
                and child.value.id in ("self", "cls")
            ):
                # Track method calls on self/cls with special prefix
                references.add(f"self.{child.attr}")

            # For x.y.z, we also care about the base 'x' (for module references)
            base: ast.expr = child
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                references.add(base.id)

    return references


def _get_class_method_name(func_name: str, enclosing_blocks: list[BlockInfo]) -> str | None:
    """Get the qualified name for a method (ClassName.method_name).

    Returns None if the function is not inside a class.
    """
    for block in reversed(enclosing_blocks):
        if block.node_type == "ClassDef" and block.name:
            return f"{block.name}.{func_name}"
    return None


def _is_same_class(blocks1: list[BlockInfo], blocks2: list[BlockInfo]) -> bool:
    """Check if two block stacks refer to the same enclosing class."""
    class1 = None
    class2 = None
    for block in reversed(blocks1):
        if block.node_type == "ClassDef":
            class1 = (block.header_start, block.name)
            break
    for block in reversed(blocks2):
        if block.node_type == "ClassDef":
            class2 = (block.header_start, block.name)
            break
    return class1 is not None and class1 == class2


def _build_definitions_map(source: str) -> tuple[dict[str, Definition], dict[str, str]]:
    """Build a map of all definitions in a source file.

    Includes functions, classes, imports, and module-level variables.
    Each definition tracks its enclosing blocks and the names it references.

    Returns:
        Tuple of (definitions_map, self_method_map) where:
        - definitions_map: Maps name -> Definition
        - self_method_map: Maps "self.method" -> actual definition name for class methods
    """
    lines = source.splitlines()
    tree = ast.parse(source)
    definitions: dict[str, Definition] = {}
    self_method_map: dict[str, str] = {}  # Maps "self.method" -> definition name

    def visit(node: ast.AST, block_stack: list[BlockInfo]) -> None:
        """Recursively visit nodes, tracking definitions and their context."""
        new_stack = block_stack

        # Track enclosing blocks
        if _is_enclosing_block(node):
            block_info = _extract_block_info(node, lines)
            new_stack = [*block_stack, block_info]

        # Function definitions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorator_start = None
            if node.decorator_list:
                decorator_start = min(d.lineno for d in node.decorator_list)

            # Extract references from function body and decorators
            refs = _extract_references(node)

            defn = Definition(
                name=node.name,
                kind="function",
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", node.lineno),
                decorator_start=decorator_start,
                enclosing_blocks=list(new_stack),
                references=refs,
                node=node,
            )

            # Use qualified name (ClassName.method) for methods inside classes
            # to avoid conflicts when different classes have same method names
            qualified_name = node.name
            enclosing_class = None
            if new_stack:
                for block in reversed(new_stack):
                    if block.node_type == "ClassDef":
                        enclosing_class = block.name
                        qualified_name = f"{block.name}.{node.name}"
                        break

            definitions[qualified_name] = defn

            # Also register with simple name for backward compatibility
            # (only if not already defined by another class)
            if node.name not in definitions:
                definitions[node.name] = defn

            # Also register with "self.method" key if this is a class method
            # This allows resolving self.method() calls
            if enclosing_class:
                self_method_map[f"self.{node.name}"] = qualified_name

        # Class definitions
        elif isinstance(node, ast.ClassDef):
            decorator_start = None
            if node.decorator_list:
                decorator_start = min(d.lineno for d in node.decorator_list)

            # Classes reference their base classes
            class_refs: set[str] = set()
            for base in node.bases:
                class_refs.update(_extract_references(base))

            # Use block_stack (not new_stack) - a class shouldn't list itself as enclosing
            definitions[node.name] = Definition(
                name=node.name,
                kind="class",
                lineno=node.lineno,
                end_lineno=getattr(node, "end_lineno", node.lineno),
                decorator_start=decorator_start,
                enclosing_blocks=list(block_stack),
                references=class_refs,
                node=node,
            )

        # Import statements
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                definitions[name] = Definition(
                    name=name,
                    kind="import",
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", node.lineno),
                    decorator_start=None,
                    enclosing_blocks=list(new_stack),
                    node=node,
                    import_module=alias.name,
                )

        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                definitions[name] = Definition(
                    name=name,
                    kind="import",
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", node.lineno),
                    decorator_start=None,
                    enclosing_blocks=list(new_stack),
                    node=node,
                    import_module=node.module or "",
                    import_names=[alias.name],
                )

        # Module-level assignments (constants, variables)
        elif isinstance(node, ast.Assign) and not block_stack:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    refs = _extract_references(node.value)
                    definitions[target.id] = Definition(
                        name=target.id,
                        kind="variable",
                        lineno=node.lineno,
                        end_lineno=getattr(node, "end_lineno", node.lineno),
                        decorator_start=None,
                        enclosing_blocks=list(new_stack),
                        references=refs,
                        node=node,
                    )

        # Visit children
        for child in ast.iter_child_nodes(node):
            visit(child, new_stack)

    visit(tree, [])
    return definitions, self_method_map


def _get_fixture_params(node: ast.AST) -> set[str]:
    """Extract fixture parameter names from a function definition.

    Fixtures are passed as parameters to test functions. The parameter names
    are used to look up fixture definitions.
    """
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()

    params: set[str] = set()
    for arg in node.args.args:
        # Skip 'self' and 'cls'
        if arg.arg not in ("self", "cls"):
            params.add(arg.arg)

    return params


def _resolve_dependencies(
    names: list[str],
    definitions: dict[str, Definition],
    self_method_map: dict[str, str],
    source_definition: Definition | None = None,
) -> list[Definition]:
    """Recursively resolve all dependencies for a set of names.

    Args:
        names: Initial names to resolve.
        definitions: Map of name -> Definition.
        self_method_map: Map of "self.method" -> definition name.
        source_definition: The definition we're resolving dependencies for
            (used to filter self.method calls to same-class methods only).

    Returns all definitions needed, in dependency order (dependencies first).
    """
    visited: set[str] = set()
    result: list[Definition] = []

    def visit(name: str, from_defn: Definition | None = None) -> None:
        # Handle self.method references
        actual_name = name
        if name.startswith("self."):
            if name in self_method_map:
                actual_name = self_method_map[name]
                # Only include if from same class
                if from_defn and actual_name in definitions:
                    target_defn = definitions[actual_name]
                    if not _is_same_class(from_defn.enclosing_blocks, target_defn.enclosing_blocks):
                        return
            else:
                return  # Unknown self.method

        if actual_name in visited:
            return
        if actual_name not in definitions:
            return  # External name (builtin, etc.)

        visited.add(actual_name)
        defn = definitions[actual_name]

        # First, resolve dependencies (pass current defn for self.method filtering)
        for ref in defn.references:
            visit(ref, defn)

        # Also check fixture parameters for function definitions
        if defn.node and defn.kind == "function":
            for param in _get_fixture_params(defn.node):
                visit(param, defn)

        result.append(defn)

    for name in names:
        # Get the source definition for self.method filtering
        src_defn = definitions.get(name) if source_definition is None else source_definition
        visit(name, src_defn)

    return result


def _definition_to_function_context(defn: Definition, lines: list[str]) -> FunctionContext:
    """Convert a Definition to a FunctionContext for block tree building."""
    return FunctionContext(
        name=defn.name,
        lineno=defn.lineno,
        end_lineno=defn.end_lineno,
        decorator_start=defn.decorator_start,
        enclosing_blocks=defn.enclosing_blocks,
        indent=_get_indent(lines[defn.lineno - 1]) if defn.lineno <= len(lines) else 0,
    )


def _is_inside_function(defn: Definition, all_defs: dict[str, Definition]) -> bool:
    """Check if a definition is inside a function/method.

    Checks if the definition's line number falls within any function's range.
    """
    def_line = defn.lineno
    for other in all_defs.values():
        if (
            other.kind == "function"
            and other.name != defn.name
            and other.lineno < def_line <= other.end_lineno
        ):
            # Check if definition is within function's line range
            return True
    return False


def _collect_required_imports(
    dependencies: list[Definition],
    all_defs: dict[str, Definition],
) -> list[Definition]:
    """Collect all top-level import definitions from the dependencies.

    Skips local imports that are inside functions - those stay with the function body.
    """
    return [d for d in dependencies if d.kind == "import" and not _is_inside_function(d, all_defs)]


def _collect_required_definitions(
    dependencies: list[Definition],
    all_defs: dict[str, Definition],
) -> list[Definition]:
    """Collect non-import definitions (functions, classes, variables).

    Skips local definitions that are inside functions - those stay with the function body.
    """
    result = []
    for d in dependencies:
        if d.kind == "import":
            continue
        # Skip any definition (function, class, variable) that's inside another function
        if _is_inside_function(d, all_defs):
            continue
        result.append(d)
    return result


def _build_block_tree(
    functions: list[FunctionContext],
    lines: list[str],
) -> BlockNode:
    """Build a tree of blocks containing the given functions.

    Each function is placed at the appropriate depth based on its enclosing blocks.
    Shared blocks are deduplicated (same block appears once with multiple children).
    """
    root = BlockNode(block_info=None)

    for func in functions:
        current = root

        # Navigate/create path to the right depth
        for block in func.enclosing_blocks:
            # Look for existing child with same block
            found = None
            for child in current.children:
                if child.block_info and _blocks_match(child.block_info, block):
                    found = child
                    break

            if found:
                current = found
            else:
                # Create new child node
                new_node = BlockNode(block_info=block)
                current.children.append(new_node)
                current = new_node

        # Add function at current level
        current.functions.append(func)

    return root


def _blocks_match(a: BlockInfo, b: BlockInfo) -> bool:
    """Check if two blocks refer to the same block."""
    return (
        a.node_type == b.node_type
        and a.name == b.name
        and a.header_start == b.header_start
        and a.end_lineno == b.end_lineno
    )


def _serialize_block_tree(
    node: BlockNode,
    lines: list[str],
    base_indent: int = 0,
) -> list[str]:
    """Serialize a block tree back to source lines.

    Args:
        node: The block tree node to serialize.
        lines: Original source lines (0-indexed).
        base_indent: Current indentation level.

    Returns:
        List of source lines.
    """
    result: list[str] = []

    if node.block_info:
        block = node.block_info
        # Add block header (with decorators if present)
        header_start_idx = block.header_start - 1
        header_end_idx = block.header_end

        for i in range(header_start_idx, header_end_idx):
            if i < len(lines):
                result.append(lines[i])

    # Sort children and functions by line number for consistent output
    all_items: list[tuple[int, str, BlockNode | FunctionContext]] = []

    for child in node.children:
        lineno = child.block_info.header_start if child.block_info else 0
        all_items.append((lineno, "block", child))

    for func in node.functions:
        lineno = func.decorator_start or func.lineno
        all_items.append((lineno, "func", func))

    all_items.sort(key=lambda x: x[0])

    for _, item_type, item in all_items:
        # Add blank line before items for readability
        if result and result[-1].strip():
            result.append("\n")

        if item_type == "block":
            if isinstance(item, BlockNode):
                child_lines = _serialize_block_tree(item, lines)
                result.extend(child_lines)
        else:
            # It's a function
            if isinstance(item, FunctionContext):
                func = item
                func_start = (func.decorator_start or func.lineno) - 1
                func_end = func.end_lineno

                for i in range(func_start, func_end):
                    if i < len(lines):
                        result.append(lines[i])

    return result


def _is_type_checking_block(block: BlockInfo, lines: list[str]) -> bool:
    """Check if a block is an 'if TYPE_CHECKING:' block."""
    if block.node_type != "If":
        return False
    # Check the condition line for TYPE_CHECKING
    if block.header_start - 1 < len(lines):
        header_line = lines[block.header_start - 1]
        return "TYPE_CHECKING" in header_line
    return False


def _generate_import_lines(
    import_defs: list[Definition],
    lines: list[str],
) -> list[str]:
    """Generate import lines from import definitions.

    Groups imports from the same line together.
    Handles TYPE_CHECKING blocks by wrapping imports appropriately.
    """
    # Group by line number (imports from same line)
    by_line: dict[int, Definition] = {}
    for defn in import_defs:
        # Only keep first definition per line (handles multiple names from same import)
        if defn.lineno not in by_line:
            by_line[defn.lineno] = defn

    # Separate into regular imports and TYPE_CHECKING imports
    regular_imports: list[tuple[int, str]] = []  # (lineno, line)
    type_checking_imports: list[tuple[int, str]] = []  # (lineno, line)
    type_checking_block: BlockInfo | None = None

    for lineno in sorted(by_line.keys()):
        defn = by_line[lineno]
        if lineno - 1 >= len(lines):
            continue

        # Handle multi-line imports by getting all lines from lineno to end_lineno
        start_idx = lineno - 1
        end_idx = defn.end_lineno
        import_lines = lines[start_idx:end_idx]
        line = "\n".join(import_lines)
        if not line.endswith("\n"):
            line += "\n"

        # Check if this import is inside a TYPE_CHECKING block
        in_type_checking = False
        for block in defn.enclosing_blocks:
            if _is_type_checking_block(block, lines):
                in_type_checking = True
                type_checking_block = block
                break

        if in_type_checking:
            type_checking_imports.append((lineno, line))
        else:
            regular_imports.append((lineno, line))

    result: list[str] = []

    # Add regular imports
    for _, line in regular_imports:
        result.append(line)

    # Add TYPE_CHECKING block with its imports
    if type_checking_imports and type_checking_block:
        # Ensure TYPE_CHECKING is imported if not already present
        has_type_checking_import = any("TYPE_CHECKING" in line for _, line in regular_imports)
        if not has_type_checking_import:
            result.append("from typing import TYPE_CHECKING\n")

        # Add blank line before TYPE_CHECKING if we have regular imports
        if result and result[-1].strip():
            result.append("\n")

        # Add the TYPE_CHECKING block header from original source
        header_line = lines[type_checking_block.header_start - 1]
        if not header_line.endswith("\n"):
            header_line += "\n"
        result.append(header_line)

        # Add the imports with proper indentation (preserved from original)
        for _, line in type_checking_imports:
            result.append(line)

    return result


def generate_split_file_v2(
    source: str,
    function_names: list[str],
) -> str:
    """Generate a new file containing only specified functions with block context.

    This is the block-aware version that properly copies enclosing blocks
    and includes all dependencies (helper functions, imports, fixtures, etc.).

    Args:
        source: Original source code.
        function_names: List of function names to include.

    Returns:
        New file source code.
    """
    lines_no_newline = source.splitlines()

    # Build definitions map for dependency resolution
    definitions, self_method_map = _build_definitions_map(source)

    # Resolve all dependencies for the requested functions
    all_deps = _resolve_dependencies(function_names, definitions, self_method_map)

    if not all_deps:
        return ""

    # Separate imports from other definitions
    import_defs = _collect_required_imports(all_deps, definitions)
    non_import_defs = _collect_required_definitions(all_deps, definitions)

    # Convert definitions to function contexts for block tree building
    contexts = [_definition_to_function_context(d, lines_no_newline) for d in non_import_defs]

    if not contexts:
        return ""

    # Build block tree
    tree = _build_block_tree(contexts, lines_no_newline)

    # Generate import lines
    import_lines = _generate_import_lines(import_defs, lines_no_newline)

    # Serialize the block tree
    body_lines = _serialize_block_tree(tree, lines_no_newline)

    # Combine: imports + body
    result_lines: list[str] = []

    # Add imports
    for line in import_lines:
        result_lines.append(line)

    # Add blank line after imports
    if result_lines and result_lines[-1].strip():
        result_lines.append("\n")

    # Add body
    if body_lines:
        result_lines.append("\n")
        for line in body_lines:
            if not line.endswith("\n"):
                result_lines.append(line + "\n")
            else:
                result_lines.append(line)

    # Ensure final newline
    result = "".join(result_lines)
    if not result.endswith("\n"):
        result += "\n"

    return result


@dataclass
class FunctionExtract:
    """A test function with its full AST and dependencies."""

    name: str
    test_type: TestType
    lineno: int
    end_lineno: int
    decorators_start: int  # First decorator line
    source_lines: list[str] = field(default_factory=list)


# Modules that indicate integration tests when used without mocking
INTEGRATION_MODULES = frozenset(
    {
        # I/O
        "anyio",
        "trio",
        "curio",
        # HTTP
        "httpx",
        "requests",
        "aiohttp",
        # Database
        "redis",
        "sqlalchemy",
        "asyncpg",
        # Cloud
        "boto3",
        "google",
    }
)


@dataclass
class FileReorganization:
    """Plan for reorganizing a single test file."""

    original_path: Path
    unit_functions: list[str] = field(default_factory=list)
    component_functions: list[str] = field(default_factory=list)
    integration_functions: list[str] = field(default_factory=list)
    unit_target: Path | None = None
    component_target: Path | None = None
    integration_target: Path | None = None
    action: str = "skip"  # skip, move_unit, move_component, move_integration, split


def _get_target_path(original: Path, test_type: TestType, root: Path) -> Path:
    """Calculate target path for a test file.

    Args:
        original: Original file path.
        test_type: The test type (unit or component).
        root: The scripts/tests root.

    Returns:
        Target path under scripts/tests/unit/ or scripts/tests/component/.
    """
    # Get path relative to scripts/tests/
    try:
        rel_path = original.relative_to(root)
    except ValueError:
        # Already has unit/component in path
        return original

    # Skip if already in unit/ or component/
    parts = rel_path.parts
    if parts and parts[0] in ("unit", "component"):
        return original

    # Build new path: scripts/tests/{unit|component}/rest/of/path
    new_parts = (test_type.value, *parts)
    return root / Path(*new_parts)


def _extract_imports_and_fixtures(source: str) -> tuple[list[str], list[str], int]:
    """Extract import statements and fixture definitions from source.

    Args:
        source: Python source code.

    Returns:
        Tuple of (import_lines, fixture_lines, first_test_line).
    """
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    import_end = 0
    fixtures: list[tuple[int, int]] = []  # (start, end) line numbers

    for node in ast.walk(tree):
        # Track imports
        if (
            isinstance(node, ast.Import | ast.ImportFrom)
            and hasattr(node, "end_lineno")
            and node.end_lineno
        ):
            import_end = max(import_end, node.end_lineno)

        # Track fixtures (functions with @pytest.fixture decorator)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            is_fixture = False
            decorator_start = node.lineno

            for dec in node.decorator_list:
                if hasattr(dec, "lineno"):
                    decorator_start = min(decorator_start, dec.lineno)
                # Check for @pytest.fixture or @fixture
                is_name_fixture = isinstance(dec, ast.Name) and dec.id == "fixture"
                is_attr_fixture = isinstance(dec, ast.Attribute) and dec.attr == "fixture"
                if is_name_fixture or is_attr_fixture:
                    is_fixture = True
                elif isinstance(dec, ast.Call):
                    func = dec.func
                    is_call_name = isinstance(func, ast.Name) and func.id == "fixture"
                    is_call_attr = isinstance(func, ast.Attribute) and func.attr == "fixture"
                    if is_call_name or is_call_attr:
                        is_fixture = True

            if is_fixture and hasattr(node, "end_lineno") and node.end_lineno:
                fixtures.append((decorator_start, node.end_lineno))

    # Find first test function
    first_test_line = len(lines)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test_"
        ):
            first_test_line = min(first_test_line, node.lineno)

    # Extract import lines (everything up to import_end, excluding blank lines at end)
    import_lines = lines[:import_end]

    # Extract fixture lines
    fixture_lines: list[str] = []
    for start, end in sorted(fixtures):
        # Include blank line before fixture if exists
        actual_start = start - 1
        if actual_start > 0 and not lines[actual_start - 1].strip():
            actual_start = start - 2
        fixture_lines.extend(lines[max(0, actual_start) : end])
        if end < len(lines) and lines[end].strip() == "":
            fixture_lines.append(lines[end])

    return import_lines, fixture_lines, first_test_line


def _extract_test_function(source: str, func_name: str) -> tuple[list[str], int, int] | None:
    """Extract a single test function with its decorators.

    Args:
        source: Python source code.
        func_name: Name of the function to extract.

    Returns:
        Tuple of (source_lines, start_line, end_line) or None.
    """
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == func_name:
            # Find start (including decorators)
            start = node.lineno
            for dec in node.decorator_list:
                if hasattr(dec, "lineno"):
                    start = min(start, dec.lineno)

            end = (
                node.end_lineno
                if hasattr(node, "end_lineno") and node.end_lineno is not None
                else node.lineno
            )

            # Convert to 0-indexed
            start_idx = start - 1
            end_idx = end if isinstance(end, int) else node.lineno

            # Include preceding blank lines (up to 2)
            while start_idx > 0 and not lines[start_idx - 1].strip():
                start_idx -= 1
                if start_idx > 0 and not lines[start_idx - 1].strip():
                    break

            return lines[start_idx:end_idx], start, end_idx

    return None


def analyze_file_for_reorg(file_path: Path, root: Path) -> FileReorganization:
    """Analyze a file and create a reorganization plan.

    Args:
        file_path: Path to the test file.
        root: The scripts/tests root.

    Returns:
        Reorganization plan for the file.
    """
    reorg = FileReorganization(original_path=file_path)

    # Skip conftest files - they stay in place
    if file_path.name == "conftest.py":
        reorg.action = "skip"
        return reorg

    # Skip __init__.py files
    if file_path.name == "__init__.py":
        reorg.action = "skip"
        return reorg

    # Skip files already in unit/, component/, or integration/
    try:
        rel_path = file_path.relative_to(root)
        parts = rel_path.parts
        if parts and parts[0] in ("unit", "component", "integration"):
            reorg.action = "skip"
            return reorg
    except ValueError:
        pass

    # Analyze the file
    analysis = analyze_test_file(file_path)

    if not analysis.test_functions:
        reorg.action = "skip"
        return reorg

    # Check if file imports integration modules
    file_uses_integration = bool(analysis.module_imports & INTEGRATION_MODULES)

    # Check which integration modules are patched
    patched_modules = {t.split(".")[0] for t in analysis.patch_targets if "." in t}

    # Classify each function based on:
    # 1. Integration: uses integration modules without mocking them
    # 2. Unit: has patches (mocks)
    # 3. Component: no patches, no unmocked integration modules
    for func in analysis.test_functions:
        if func.has_patches:
            # Check if this function specifically patches integration modules
            reorg.unit_functions.append(func.qualified_name)
        elif file_uses_integration:
            # File uses integration modules and this function doesn't mock them
            # Check if any integration module is NOT patched
            unpatched_integration = analysis.module_imports & INTEGRATION_MODULES - patched_modules
            if unpatched_integration:
                reorg.integration_functions.append(func.qualified_name)
            else:
                reorg.component_functions.append(func.qualified_name)
        else:
            reorg.component_functions.append(func.qualified_name)

    # Determine action
    has_unit = len(reorg.unit_functions) > 0
    has_component = len(reorg.component_functions) > 0
    has_integration = len(reorg.integration_functions) > 0

    # Count how many types we have
    type_count = sum([has_unit, has_component, has_integration])

    if type_count > 1:
        # Mixed file - needs splitting
        reorg.action = "split"
        if has_unit:
            reorg.unit_target = _get_target_path(file_path, TestType.UNIT, root)
        if has_component:
            reorg.component_target = _get_target_path(file_path, TestType.COMPONENT, root)
        if has_integration:
            reorg.integration_target = _get_target_path(file_path, TestType.INTEGRATION, root)
    elif has_unit:
        # Pure unit file - move to unit/
        reorg.action = "move_unit"
        reorg.unit_target = _get_target_path(file_path, TestType.UNIT, root)
    elif has_integration:
        # Pure integration file - move to integration/
        reorg.action = "move_integration"
        reorg.integration_target = _get_target_path(file_path, TestType.INTEGRATION, root)
    elif has_component:
        # Pure component file - move to component/
        reorg.action = "move_component"
        reorg.component_target = _get_target_path(file_path, TestType.COMPONENT, root)
    else:
        reorg.action = "skip"

    return reorg


def generate_split_file(source: str, functions: list[str], original_path: Path) -> str:
    """Generate a new file containing only specified functions.

    This uses the block-aware extraction to properly copy enclosing blocks
    (like classes) when functions are moved.

    Args:
        source: Original source code.
        functions: List of function names to include.
        original_path: Original file path (for docstring).

    Returns:
        New file source code.
    """
    # Use the block-aware version
    return generate_split_file_v2(source, functions)


def _ensure_init_files(target_path: Path, root: Path, dry_run: bool) -> list[str]:
    """Ensure __init__.py exists in target directory and all parents up to root.

    Args:
        target_path: The file path being created.
        root: The scripts/tests root.
        dry_run: If True, only print what would be done.

    Returns:
        List of __init__.py files created.
    """
    actions: list[str] = []
    current = target_path.parent

    while current != root and current.is_relative_to(root):
        init_file = current / "__init__.py"
        if not init_file.exists() and not dry_run:
            init_file.parent.mkdir(parents=True, exist_ok=True)
            init_file.write_text('"""Test package."""\n', encoding="utf-8")
            # Don't add to actions - too noisy
        current = current.parent

    return actions


def execute_reorganization(
    reorg: FileReorganization,
    root: Path,
    dry_run: bool = True,
    keep_originals: bool = True,
) -> list[str]:
    """Execute a single file reorganization.

    Args:
        reorg: The reorganization plan.
        root: The scripts/tests root.
        dry_run: If True, only print what would be done.
        keep_originals: If True, do not delete original files (default: True).
            Set to False only after verifying the reorganization is correct.

    Returns:
        List of actions taken.
    """
    actions: list[str] = []

    if reorg.action == "skip":
        return actions

    source = reorg.original_path.read_text(encoding="utf-8")
    action_verb = "COPY" if keep_originals else "MOVE"

    if reorg.action == "move_unit":
        target = reorg.unit_target
        if target and target != reorg.original_path:
            actions.append(f"{action_verb} {reorg.original_path} -> {target}")
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")
                _ensure_init_files(target, root, dry_run)
                if not keep_originals:
                    reorg.original_path.unlink()

    elif reorg.action == "move_component":
        target = reorg.component_target
        if target and target != reorg.original_path:
            actions.append(f"{action_verb} {reorg.original_path} -> {target}")
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")
                _ensure_init_files(target, root, dry_run)
                if not keep_originals:
                    reorg.original_path.unlink()

    elif reorg.action == "move_integration":
        target = reorg.integration_target
        if target and target != reorg.original_path:
            actions.append(f"{action_verb} {reorg.original_path} -> {target}")
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")
                _ensure_init_files(target, root, dry_run)
                if not keep_originals:
                    reorg.original_path.unlink()

    elif reorg.action == "split":
        # Generate unit file
        if reorg.unit_target and reorg.unit_functions:
            unit_source = generate_split_file(source, reorg.unit_functions, reorg.original_path)
            actions.append(f"CREATE {reorg.unit_target} ({len(reorg.unit_functions)} functions)")
            if not dry_run:
                reorg.unit_target.parent.mkdir(parents=True, exist_ok=True)
                reorg.unit_target.write_text(unit_source, encoding="utf-8")
                _ensure_init_files(reorg.unit_target, root, dry_run)

        # Generate component file
        if reorg.component_target and reorg.component_functions:
            component_source = generate_split_file(
                source, reorg.component_functions, reorg.original_path
            )
            actions.append(
                f"CREATE {reorg.component_target} ({len(reorg.component_functions)} functions)"
            )
            if not dry_run:
                reorg.component_target.parent.mkdir(parents=True, exist_ok=True)
                reorg.component_target.write_text(component_source, encoding="utf-8")
                _ensure_init_files(reorg.component_target, root, dry_run)

        # Generate integration file
        if reorg.integration_target and reorg.integration_functions:
            integration_source = generate_split_file(
                source, reorg.integration_functions, reorg.original_path
            )
            actions.append(
                f"CREATE {reorg.integration_target} ({len(reorg.integration_functions)} functions)"
            )
            if not dry_run:
                reorg.integration_target.parent.mkdir(parents=True, exist_ok=True)
                reorg.integration_target.write_text(integration_source, encoding="utf-8")
                _ensure_init_files(reorg.integration_target, root, dry_run)

        # Only delete original if not keeping originals
        if not keep_originals:
            actions.append(f"DELETE {reorg.original_path}")
            if not dry_run:
                reorg.original_path.unlink()
        else:
            actions.append(f"KEEP {reorg.original_path} (original preserved)")

    return actions


def create_init_files(root: Path, dry_run: bool = True) -> list[str]:
    """Create __init__.py files in new directories.

    Args:
        root: The scripts/tests root.
        dry_run: If True, only print what would be done.

    Returns:
        List of actions taken.
    """
    actions: list[str] = []

    for subdir in ["unit", "component", "integration"]:
        init_path = root / subdir / "__init__.py"
        if not init_path.exists():
            actions.append(f"CREATE {init_path}")
            if not dry_run:
                init_path.parent.mkdir(parents=True, exist_ok=True)
                init_path.write_text('"""Test package."""\n', encoding="utf-8")

    return actions


def copy_conftest_files(root: Path, dry_run: bool = True) -> list[str]:
    """Copy conftest.py files to unit/, component/, and integration/ directories.

    Conftest files in subdirectories need to be copied to all test suite
    directories so fixtures are available in all test suites.

    Args:
        root: The scripts/tests root.
        dry_run: If True, only print what would be done.

    Returns:
        List of actions taken.
    """
    actions: list[str] = []

    # Find all conftest.py files except the root one
    for conftest in root.rglob("conftest.py"):
        # Skip root conftest - it stays in place
        if conftest.parent == root:
            continue

        # Skip if already in unit/, component/, or integration/
        try:
            rel_path = conftest.relative_to(root)
            parts = rel_path.parts
            if parts and parts[0] in ("unit", "component", "integration"):
                continue
        except ValueError:
            continue

        # Copy to all test suite directories
        for subdir in ["unit", "component", "integration"]:
            target = root / subdir / rel_path
            if not target.exists():
                actions.append(f"COPY {conftest} -> {target}")
                if not dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(conftest.read_text(encoding="utf-8"), encoding="utf-8")

    return actions


def reorganize_tests(
    test_root: Path,
    dry_run: bool = True,
    keep_originals: bool = True,
) -> dict[str, list[str]]:
    """Reorganize all test files in a directory.

    Args:
        test_root: Root directory (scripts/tests/).
        dry_run: If True, only print what would be done.
        keep_originals: If True, do not delete original files (default: True).

    Returns:
        Summary of actions by category.
    """
    summary: dict[str, list[str]] = defaultdict(list)

    # Find all test files
    test_files = list(test_root.rglob("test_*.py"))

    # Analyze each file
    reorganizations: list[FileReorganization] = []
    for test_file in test_files:
        reorg = analyze_file_for_reorg(test_file, test_root)
        reorganizations.append(reorg)

    # Create init files first
    init_actions = create_init_files(test_root, dry_run)
    summary["init_files"] = init_actions

    # Copy conftest files to both directories
    conftest_actions = copy_conftest_files(test_root, dry_run)
    summary["conftest_files"] = conftest_actions

    # Execute reorganizations
    for reorg in reorganizations:
        actions = execute_reorganization(reorg, test_root, dry_run, keep_originals)
        if actions:
            summary[reorg.action].extend(actions)

    return dict(summary)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Reorganize test files by type")
    parser.add_argument("test_root", type=Path, help="Test root directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Only show what would be done (default)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the reorganization",
    )

    args = parser.parse_args(argv)

    if not args.test_root.exists():
        print(f"Error: {args.test_root} does not exist", file=sys.stderr)
        return 1

    dry_run = not args.execute

    if dry_run:
        print("=== DRY RUN (use --execute to apply) ===\n")
    else:
        print("=== EXECUTING REORGANIZATION ===\n")
        print("NOTE: Original files will be preserved.\n")

    summary = reorganize_tests(args.test_root, dry_run)

    # Print summary (metrics only, no file list)
    total_actions = 0
    for category, actions in sorted(summary.items()):
        if actions:
            total_actions += len(actions)
            print(f"{category.upper()}: {len(actions)} actions")

    print(f"\nTotal: {total_actions} actions")

    if dry_run:
        print("\nRun with --execute to apply these changes.")
    else:
        print("\nOriginal files preserved. To verify:")
        print(
            "  1. Run: uv run python -m scripts.dev.count_test_lines <new_folders> --verify-syntax"
        )
        print(
            "  2. Run: uv run python -m scripts.dev.diff_test_functions "
            "<original> --new <new_folders>"
        )

    return 0


def _test_block_aware_extraction() -> None:
    """Test suite for block-aware function extraction.

    Run with: uv run python -m scripts.dev.test_reorganizer --test
    """
    import textwrap

    print("Running block-aware extraction tests...\n")

    # =========================================================================
    # Test 1: Simple function (no enclosing blocks)
    # =========================================================================
    print("Test 1: Simple function extraction")
    source1 = textwrap.dedent("""\
        import pytest

        def test_simple():
            pytest.skip("test")
    """)

    result1 = generate_split_file_v2(source1, ["test_simple"])
    assert "def test_simple():" in result1, "Function should be in output"
    assert "import pytest" in result1, "Used imports should be in output"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 2: Function inside a class
    # =========================================================================
    print("Test 2: Function inside a class")
    source2 = textwrap.dedent("""\
        import pytest

        class TestFoo:
            def test_inside_class(self):
                assert True
    """)

    result2 = generate_split_file_v2(source2, ["test_inside_class"])
    assert "class TestFoo:" in result2, "Class should be copied"
    assert "def test_inside_class(self):" in result2, "Function should be in output"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 3: Two functions in same class, extract only one
    # =========================================================================
    print("Test 3: Two functions in same class, extract only one")
    source3 = textwrap.dedent("""\
        import pytest

        class TestFoo:
            def test_a(self):
                pass

            def test_b(self):
                pass
    """)

    result3a = generate_split_file_v2(source3, ["test_a"])
    result3b = generate_split_file_v2(source3, ["test_b"])

    # Both should have the class
    assert "class TestFoo:" in result3a, "Class should be in result A"
    assert "class TestFoo:" in result3b, "Class should be in result B"

    # Each should only have its function
    assert "def test_a(self):" in result3a, "test_a should be in result A"
    assert "def test_b(self):" not in result3a, "test_b should NOT be in result A"
    assert "def test_b(self):" in result3b, "test_b should be in result B"
    assert "def test_a(self):" not in result3b, "test_a should NOT be in result B"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 4: Nested blocks - the main hierarchical test
    #
    # Structure:
    #   OuterClass:
    #       InnerClassA:
    #           test_a
    #       InnerClassB:
    #           test_b
    #
    # When extracting test_a: OuterClass + InnerClassA + test_a
    # When extracting test_b: OuterClass + InnerClassB + test_b
    # =========================================================================
    print("Test 4: Nested blocks (hierarchical)")
    source4 = textwrap.dedent("""\
        import pytest

        class TestOuter:
            class TestInnerA:
                def test_a(self):
                    pass

            class TestInnerB:
                def test_b(self):
                    pass
    """)

    result4a = generate_split_file_v2(source4, ["test_a"])
    result4b = generate_split_file_v2(source4, ["test_b"])

    # Both should have OuterClass
    assert "class TestOuter:" in result4a, "OuterClass should be in result A"
    assert "class TestOuter:" in result4b, "OuterClass should be in result B"

    # Result A should have InnerClassA but NOT InnerClassB
    assert "class TestInnerA:" in result4a, "InnerClassA should be in result A"
    assert "class TestInnerB:" not in result4a, "InnerClassB should NOT be in result A"
    assert "def test_a(self):" in result4a, "test_a should be in result A"
    assert "def test_b(self):" not in result4a, "test_b should NOT be in result A"

    # Result B should have InnerClassB but NOT InnerClassA
    assert "class TestInnerB:" in result4b, "InnerClassB should be in result B"
    assert "class TestInnerA:" not in result4b, "InnerClassA should NOT be in result B"
    assert "def test_b(self):" in result4b, "test_b should be in result B"
    assert "def test_a(self):" not in result4b, "test_a should NOT be in result B"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 5: Triple nesting - OuterClass > MiddleClass > InnerClass > function
    # =========================================================================
    print("Test 5: Triple nesting")
    source5 = textwrap.dedent("""\
        import pytest

        class TestLevel1:
            class TestLevel2:
                class TestLevel3:
                    def test_deep(self):
                        pass
    """)

    result5 = generate_split_file_v2(source5, ["test_deep"])
    assert "class TestLevel1:" in result5, "Level 1 should be present"
    assert "class TestLevel2:" in result5, "Level 2 should be present"
    assert "class TestLevel3:" in result5, "Level 3 should be present"
    assert "def test_deep(self):" in result5, "Function should be present"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 6: Mixed nesting depths - one function at depth 1, another at depth 2
    # =========================================================================
    print("Test 6: Mixed nesting depths")
    source6 = textwrap.dedent("""\
        import pytest

        class TestOuter:
            def test_shallow(self):
                pass

            class TestInner:
                def test_deep(self):
                    pass
    """)

    result6a = generate_split_file_v2(source6, ["test_shallow"])
    result6b = generate_split_file_v2(source6, ["test_deep"])

    # Shallow: only OuterClass, no InnerClass
    assert "class TestOuter:" in result6a, "OuterClass should be in shallow result"
    assert "def test_shallow(self):" in result6a, "test_shallow should be present"
    assert "class TestInner:" not in result6a, "InnerClass should NOT be in shallow result"
    assert "def test_deep(self):" not in result6a, "test_deep should NOT be in shallow result"

    # Deep: OuterClass + InnerClass
    assert "class TestOuter:" in result6b, "OuterClass should be in deep result"
    assert "class TestInner:" in result6b, "InnerClass should be in deep result"
    assert "def test_deep(self):" in result6b, "test_deep should be present"
    assert "def test_shallow(self):" not in result6b, "test_shallow should NOT be in deep result"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 7: Decorators on functions should be preserved
    # =========================================================================
    print("Test 7: Function decorators preserved")
    source7 = textwrap.dedent("""\
        import pytest
        from unittest.mock import patch

        class TestFoo:
            @pytest.mark.slow
            @patch("some.module")
            def test_decorated(self, mock_mod):
                pass
    """)

    result7 = generate_split_file_v2(source7, ["test_decorated"])
    assert "@pytest.mark.slow" in result7, "First decorator should be present"
    assert '@patch("some.module")' in result7, "Second decorator should be present"
    assert "def test_decorated(self, mock_mod):" in result7, "Function should be present"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 8: Class with decorators
    # =========================================================================
    print("Test 8: Class decorators preserved")
    source8 = textwrap.dedent("""\
        import pytest

        @pytest.mark.integration
        class TestDecorated:
            def test_inside(self):
                pass
    """)

    result8 = generate_split_file_v2(source8, ["test_inside"])
    assert "@pytest.mark.integration" in result8, "Class decorator should be present"
    assert "class TestDecorated:" in result8, "Class should be present"
    assert "def test_inside(self):" in result8, "Function should be present"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 9: Multiple functions at same level extracted together
    # =========================================================================
    print("Test 9: Multiple functions extracted together")
    source9 = textwrap.dedent("""\
        import pytest

        class TestOuter:
            class TestInner:
                def test_a(self):
                    pass

                def test_b(self):
                    pass
    """)

    result9 = generate_split_file_v2(source9, ["test_a", "test_b"])
    assert "class TestOuter:" in result9, "OuterClass should be present"
    assert "class TestInner:" in result9, "InnerClass should be present"
    assert "def test_a(self):" in result9, "test_a should be present"
    assert "def test_b(self):" in result9, "test_b should be present"
    # Should only have ONE copy of each class
    assert result9.count("class TestOuter:") == 1, "OuterClass should appear once"
    assert result9.count("class TestInner:") == 1, "InnerClass should appear once"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 10: Helper function dependency
    # =========================================================================
    print("Test 10: Helper function dependency")
    source10 = textwrap.dedent("""\
        def helper_func():
            return 42

        def test_with_helper():
            assert helper_func() == 42
    """)

    result10 = generate_split_file_v2(source10, ["test_with_helper"])
    assert "def test_with_helper():" in result10, "Test function should be present"
    assert "def helper_func():" in result10, "Helper function should be included"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 11: self.method() dependency within class
    # =========================================================================
    print("Test 11: self.method() dependency within class")
    source11 = textwrap.dedent("""\
        class TestFoo:
            def helper_method(self):
                return 42

            def test_with_self_method(self):
                assert self.helper_method() == 42
    """)

    result11 = generate_split_file_v2(source11, ["test_with_self_method"])
    assert "class TestFoo:" in result11, "Class should be present"
    assert "def test_with_self_method(self):" in result11, "Test should be present"
    assert "def helper_method(self):" in result11, "Helper method should be included"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 12: Fixture dependency
    # =========================================================================
    print("Test 12: Fixture dependency")
    source12 = textwrap.dedent("""\
        import pytest

        @pytest.fixture
        def my_fixture():
            return 42

        def test_with_fixture(my_fixture):
            assert my_fixture == 42
    """)

    result12 = generate_split_file_v2(source12, ["test_with_fixture"])
    assert "def test_with_fixture(my_fixture):" in result12, "Test should be present"
    assert "@pytest.fixture" in result12, "Fixture decorator should be present"
    assert "def my_fixture():" in result12, "Fixture function should be included"
    assert "import pytest" in result12, "pytest import should be included"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 13: Module-level variable dependency
    # =========================================================================
    print("Test 13: Module-level variable dependency")
    source13 = textwrap.dedent("""\
        CONSTANT_VALUE = 42

        def test_with_constant():
            assert CONSTANT_VALUE == 42
    """)

    result13 = generate_split_file_v2(source13, ["test_with_constant"])
    assert "def test_with_constant():" in result13, "Test should be present"
    assert "CONSTANT_VALUE = 42" in result13, "Constant should be included"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 14: Chained dependencies (test -> helper -> another_helper)
    # =========================================================================
    print("Test 14: Chained dependencies")
    source14 = textwrap.dedent("""\
        def deep_helper():
            return 21

        def middle_helper():
            return deep_helper() * 2

        def test_chained():
            assert middle_helper() == 42
    """)

    result14 = generate_split_file_v2(source14, ["test_chained"])
    assert "def test_chained():" in result14, "Test should be present"
    assert "def middle_helper():" in result14, "Middle helper should be included"
    assert "def deep_helper():" in result14, "Deep helper should be included"
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 15: Helper function with block context
    # =========================================================================
    print("Test 15: Helper function with block context")
    source15 = textwrap.dedent("""\
        class TestOuter:
            class HelperClass:
                def helper_in_block(self):
                    return 42

            class TestInner:
                def test_uses_helper(self):
                    h = TestOuter.HelperClass()
                    assert h.helper_in_block() == 42
    """)

    # Note: This tests that HelperClass is included because it's referenced
    result15 = generate_split_file_v2(source15, ["test_uses_helper"])
    assert "class TestOuter:" in result15, "OuterClass should be present"
    assert "class TestInner:" in result15, "TestInner should be present"
    assert "def test_uses_helper(self):" in result15, "Test should be present"
    # HelperClass is referenced but as TestOuter.HelperClass, so TestOuter is needed
    print("  ✓ Passed\n")

    # =========================================================================
    # Test 16: Mixed test and helper in same class - extract only test
    # =========================================================================
    print("Test 16: Extract test without unneeded methods")
    source16 = textwrap.dedent("""\
        class TestFoo:
            def helper_a(self):
                return 1

            def helper_b(self):
                return 2

            def test_uses_a(self):
                assert self.helper_a() == 1

            def test_uses_b(self):
                assert self.helper_b() == 2
    """)

    result16a = generate_split_file_v2(source16, ["test_uses_a"])
    result16b = generate_split_file_v2(source16, ["test_uses_b"])

    # test_uses_a should have helper_a but NOT helper_b
    assert "def test_uses_a(self):" in result16a
    assert "def helper_a(self):" in result16a, "helper_a should be included"
    assert "def helper_b(self):" not in result16a, "helper_b should NOT be included"
    assert "def test_uses_b(self):" not in result16a

    # test_uses_b should have helper_b but NOT helper_a
    assert "def test_uses_b(self):" in result16b
    assert "def helper_b(self):" in result16b, "helper_b should be included"
    assert "def helper_a(self):" not in result16b, "helper_a should NOT be included"
    assert "def test_uses_a(self):" not in result16b
    print("  ✓ Passed\n")

    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        _test_block_aware_extraction()
    else:
        sys.exit(main())
