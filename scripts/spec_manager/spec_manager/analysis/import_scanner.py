"""Scan architectural source files for imports of algorithmic atom functions."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ImportHit:
    """A detected import of an atom function in an architectural file."""

    atom_name: str
    arch_file: str
    arch_location: str  # file:class.method or file:function
    import_statement: str  # The raw import line
    usage_sites: list[str] = field(default_factory=list)  # line numbers where used


def _extract_imported_atom_names(
    tree: ast.Module,
    atom_names: set[str],
) -> dict[str, str]:
    """Extract atom names imported via ``from ... import ...`` or ``import ...``.

    Returns a mapping from the local alias used in the file to the canonical
    atom name so that usage-site detection works regardless of aliasing.
    """
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                canonical = alias.name
                if canonical in atom_names:
                    local_name = alias.asname if alias.asname else canonical
                    imported[local_name] = canonical
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # ``import some.module`` -- the module name itself is unlikely
                # to be an atom, but we still check the final dotted component.
                parts = alias.name.split(".")
                tail = parts[-1]
                if tail in atom_names:
                    local_name = alias.asname if alias.asname else alias.name
                    imported[local_name] = tail
    return imported


def _collect_usage_sites(
    tree: ast.Module,
    local_names: set[str],
) -> list[str]:
    """Collect line numbers where any of *local_names* is referenced."""
    sites: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in local_names:
            sites.append(str(getattr(node, "lineno", "?")))
        elif isinstance(node, ast.Attribute):
            # Handle ``module.atom_func`` style.
            if node.attr in local_names:
                sites.append(str(getattr(node, "lineno", "?")))
    return sites


def _enclosing_scope(
    tree: ast.Module,
    lineno: int,
    file_path_str: str,
) -> str:
    """Return the enclosing class.method or function name for *lineno*."""
    best: str = file_path_str
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            if start <= lineno <= end:
                # Check for enclosing class.
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.ClassDef):
                        for child in ast.iter_child_nodes(parent):
                            if child is node:
                                best = f"{file_path_str}:{parent.name}.{node.name}"
                                break
                else:
                    candidate = f"{file_path_str}:{node.name}"
                    if len(candidate) > len(best):
                        best = candidate
    return best


def _import_statement_text(
    source_lines: list[str],
    node: ast.stmt,
) -> str:
    """Reconstruct a human-readable import statement from an AST node."""
    lineno = getattr(node, "lineno", 0)
    if 0 < lineno <= len(source_lines):
        return source_lines[lineno - 1].strip()
    return ""


def scan_file_imports(
    file_path: Path,
    atom_names: set[str],
) -> list[ImportHit]:
    """Scan a single Python file for imports of known atom functions.

    Uses AST parsing to detect:
    - ``from atoms.module import atom_func``
    - ``import atoms.module`` followed by ``atoms.module.atom_func()`` usage
    - Direct function calls matching atom names

    Args:
        file_path: Path to the architectural Python file.
        atom_names: Set of known atom function names.

    Returns:
        List of ImportHit records for detected atom imports.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Cannot read %s: %s", file_path, exc)
        return []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        logger.warning("Syntax error in %s: %s", file_path, exc)
        return []

    source_lines = source.splitlines()
    file_str = str(file_path)

    imported = _extract_imported_atom_names(tree, atom_names)
    if not imported:
        return []

    hits: list[ImportHit] = []
    for local_name, canonical_name in imported.items():
        usage_sites = _collect_usage_sites(tree, {local_name})

        # Determine the import statement text.
        import_text = ""
        for node in ast.walk(tree):
            if isinstance(node, (ast.ImportFrom, ast.Import)):
                stmt_text = _import_statement_text(source_lines, node)
                if canonical_name in stmt_text or local_name in stmt_text:
                    import_text = stmt_text
                    break

        # Determine the primary usage location (first usage site, or the
        # file-level scope if no usage was found).
        if usage_sites:
            first_lineno = int(usage_sites[0]) if usage_sites[0].isdigit() else 0
            arch_location = _enclosing_scope(tree, first_lineno, file_str)
        else:
            arch_location = file_str

        hits.append(
            ImportHit(
                atom_name=canonical_name,
                arch_file=file_str,
                arch_location=arch_location,
                import_statement=import_text,
                usage_sites=usage_sites,
            )
        )

    return hits


def scan_directory_imports(
    arch_dir: Path,
    atom_names: set[str],
    exclude_patterns: list[str] | None = None,
) -> list[ImportHit]:
    """Scan an entire directory tree for atom imports.

    Args:
        arch_dir: Root directory of architectural source files.
        atom_names: Set of known atom function names.
        exclude_patterns: Glob patterns to exclude (e.g., ``["**/tests/**"]``).

    Returns:
        Aggregated list of ImportHit records.
    """
    exclude_patterns = exclude_patterns or []
    hits: list[ImportHit] = []

    for py_file in sorted(arch_dir.rglob("*.py")):
        # Check exclusion patterns.
        rel = py_file.relative_to(arch_dir).as_posix()
        skip = False
        for pattern in exclude_patterns:
            # Simple glob-style matching: ``**/<part>/**``.
            from fnmatch import fnmatch

            if fnmatch(rel, pattern):
                skip = True
                break
        if skip:
            continue

        file_hits = scan_file_imports(py_file, atom_names)
        hits.extend(file_hits)

    return hits


def build_atom_registry(
    algorithmic_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Build a registry of atom functions from algorithmic source files.

    Parses all Python files in the algorithmic directory to extract:
    - Function names
    - File locations
    - Signatures (parameter names and types)
    - Return types

    Args:
        algorithmic_dir: Root directory of algorithmic source files.

    Returns:
        Dict mapping atom_name to metadata dict with keys:
        file, line, params, return_type.
    """
    registry: dict[str, dict[str, Any]] = {}

    if not algorithmic_dir.exists():
        logger.warning("Algorithmic directory does not exist: %s", algorithmic_dir)
        return registry

    for py_file in sorted(algorithmic_dir.rglob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Cannot read %s: %s", py_file, exc)
            continue

        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError as exc:
            logger.warning("Syntax error in %s: %s", py_file, exc)
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # Skip private/dunder helpers.
            if node.name.startswith("_"):
                continue

            params: list[str] = []
            for arg in node.args.args:
                if arg.arg == "self":
                    continue
                annotation = ""
                if arg.annotation:
                    annotation = ast.unparse(arg.annotation)
                param_str = f"{arg.arg}: {annotation}" if annotation else arg.arg
                params.append(param_str)

            return_type = ""
            if node.returns:
                return_type = ast.unparse(node.returns)

            registry[node.name] = {
                "file": str(py_file),
                "line": node.lineno,
                "params": params,
                "return_type": return_type,
            }

    return registry
