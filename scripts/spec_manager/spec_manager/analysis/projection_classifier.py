"""Classify the projection type of each architectural import of an atom."""

from __future__ import annotations

import ast
import logging

from spec_manager.analysis.import_scanner import ImportHit
from spec_manager.schemas.lineage import LineageEdge
from spec_manager.schemas.pin_functions import ProjectionType

logger = logging.getLogger(__name__)


def _count_atom_calls_in_function(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    atom_local_names: set[str],
) -> int:
    """Count distinct atom function calls inside a single function body."""
    called: set[str] = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in atom_local_names:
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute) and node.func.attr in atom_local_names:
                called.add(node.func.attr)
    return len(called)


def _function_returns_atom_directly(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    atom_local_name: str,
) -> bool:
    """Check whether the function directly returns the result of the atom call.

    A pass-through pattern looks like:
        def wrapper(...):
            return atom_func(...)
    """
    for node in ast.walk(func_node):
        if isinstance(node, ast.Return) and node.value is not None:
            if isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Name) and func.id == atom_local_name:
                    return True
                if isinstance(func, ast.Attribute) and func.attr == atom_local_name:
                    return True
    return False


def _find_enclosing_function(
    tree: ast.Module,
    target_lineno: int,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Find the function definition enclosing *target_lineno*."""
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            if start <= target_lineno <= end:
                if best is None or node.lineno > best.lineno:
                    best = node
    return best


def _get_imported_local_names(
    tree: ast.Module,
    all_atom_names: set[str],
) -> dict[str, str]:
    """Map local alias -> canonical atom name for all atom imports in the file."""
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in all_atom_names:
                    local = alias.asname if alias.asname else alias.name
                    imported[local] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                tail = alias.name.split(".")[-1]
                if tail in all_atom_names:
                    local = alias.asname if alias.asname else alias.name
                    imported[local] = tail
    return imported


def classify_import(
    hit: ImportHit,
    arch_source: str,
    all_atom_names: set[str],
) -> LineageEdge:
    """Classify a single import hit into a projection type.

    Classification rules:
    1. pass_through: The atom function is called directly and its result
       returned or assigned without modification.
    2. wrap: The atom function is called but its result is transformed,
       decorated, or augmented before use.
    3. smear: The architectural location calls multiple atom functions
       and combines their results.
    4. introduction: The architectural function does not import any atoms
       (detected separately, not via import hits).

    Args:
        hit: The import hit to classify.
        arch_source: Full source text of the architectural file.
        all_atom_names: Set of all known atom names for smear detection.

    Returns:
        A LineageEdge with the determined transformation type.
    """
    transformation: ProjectionType = ProjectionType.MIDDLEWARE_WRAP  # default fallback

    try:
        tree = ast.parse(arch_source, filename=hit.arch_file)
    except SyntaxError:
        return LineageEdge(
            from_atom=hit.atom_name,
            to_location=hit.arch_location,
            transformation=ProjectionType.MIDDLEWARE_WRAP,
            confidence=0.5,
            import_path=hit.import_statement,
            evidence="Could not parse source for classification",
        )

    # Build local-name mapping for all atoms in this file.
    local_names_map = _get_imported_local_names(tree, all_atom_names)
    atom_local_names = set(local_names_map.keys())

    # Determine the local name used for the specific hit atom.
    hit_local_name = hit.atom_name
    for local, canonical in local_names_map.items():
        if canonical == hit.atom_name:
            hit_local_name = local
            break

    # Find the enclosing function for the first usage site.
    target_lineno = 0
    if hit.usage_sites:
        first = hit.usage_sites[0]
        if first.isdigit():
            target_lineno = int(first)

    enclosing = _find_enclosing_function(tree, target_lineno) if target_lineno else None

    if enclosing is not None:
        atom_call_count = _count_atom_calls_in_function(enclosing, atom_local_names)

        if atom_call_count > 1:
            transformation = ProjectionType.SMEAR
        elif _function_returns_atom_directly(enclosing, hit_local_name):
            transformation = ProjectionType.PASS_THROUGH
        else:
            transformation = ProjectionType.MIDDLEWARE_WRAP
    else:
        # Module-level usage -- conservative classification.
        transformation = ProjectionType.MIDDLEWARE_WRAP

    return LineageEdge(
        from_atom=hit.atom_name,
        to_location=hit.arch_location,
        transformation=transformation,
        confidence=1.0,
        import_path=hit.import_statement,
    )


def classify_all_imports(
    hits: list[ImportHit],
    arch_sources: dict[str, str],
    all_atom_names: set[str],
) -> list[LineageEdge]:
    """Classify all import hits into lineage edges.

    Args:
        hits: List of import hits from the scanner.
        arch_sources: Map of file paths to source text.
        all_atom_names: Set of all known atom names.

    Returns:
        List of classified LineageEdge objects.
    """
    edges: list[LineageEdge] = []
    for hit in hits:
        source = arch_sources.get(hit.arch_file, "")
        edge = classify_import(hit, source, all_atom_names)
        edges.append(edge)
    return edges


def detect_introductions(
    arch_dir_files: list[str],
    lineage_edges: list[LineageEdge],
) -> list[str]:
    """Detect architectural files/functions with no atom imports.

    These are "introduced" algorithms -- architectural code that has
    no counterpart in the algorithmic layer.

    Args:
        arch_dir_files: All architectural file paths.
        lineage_edges: Already-classified lineage edges.

    Returns:
        List of architectural locations that are introductions.
    """
    covered_files: set[str] = set()
    for edge in lineage_edges:
        # Extract the file portion of ``to_location`` (before the colon).
        file_part = edge.to_location.split(":")[0] if ":" in edge.to_location else edge.to_location
        covered_files.add(file_part)

    introductions: list[str] = []
    for arch_file in arch_dir_files:
        if arch_file not in covered_files:
            introductions.append(arch_file)

    return sorted(introductions)
