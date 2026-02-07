"""Extract data flow summaries (signals in/out, stores touched) per atom."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

from spec_manager.schemas.lineage import DataFlowSummary

logger = logging.getLogger(__name__)


def _find_function_node(
    tree: ast.Module,
    func_name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Locate the AST node for a top-level or class-level function by name."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return node
    return None


def _extract_params(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Extract parameter names with optional type annotations."""
    params: list[str] = []
    for arg in func_node.args.args:
        if arg.arg == "self":
            continue
        if arg.annotation:
            annotation = ast.unparse(arg.annotation)
            params.append(f"{arg.arg}: {annotation}")
        else:
            params.append(arg.arg)
    return params


def _extract_return_type(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Extract return type annotation if present."""
    if func_node.returns:
        return [ast.unparse(func_node.returns)]
    return []


def _extract_store_access(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    store_definitions: dict[str, list[str]] | None,
    atom_name: str,
) -> list[str]:
    """Detect store identifiers accessed by the function.

    Uses two strategies:
    1. If *store_definitions* maps store_id -> [atom_ids], look up which
       stores list this atom.
    2. Heuristic: scan for attribute access patterns that resemble store
       operations (e.g., `self.store`, `db.get`, `cache.set`).
    """
    stores: set[str] = set()

    # Strategy 1: explicit store definitions.
    if store_definitions:
        for store_id, atom_ids in store_definitions.items():
            if atom_name in atom_ids:
                stores.add(store_id)

    # Strategy 2: heuristic detection from attribute calls.
    store_keywords = {"store", "cache", "db", "database", "repository", "repo", "registry"}
    for node in ast.walk(func_node):
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id.lower() in store_keywords:
                stores.add(f"{node.value.id}.{node.attr}")

    return sorted(stores)


def extract_data_flow(
    atom_name: str,
    file_path: Path,
    store_definitions: dict[str, list[str]] | None = None,
) -> DataFlowSummary:
    """Extract data flow summary for a single atom function.

    Analyzes:
    - Function parameters (signals_in)
    - Return type annotations or inferred returns (signals_out)
    - Calls to store-access functions (stores_touched)

    Args:
        atom_name: Name of the atom function.
        file_path: Path to the file containing the function.
        store_definitions: Optional map of store access patterns.

    Returns:
        DataFlowSummary for the atom.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Cannot read %s: %s", file_path, exc)
        return DataFlowSummary(atom_id=atom_name)

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        logger.warning("Syntax error in %s: %s", file_path, exc)
        return DataFlowSummary(atom_id=atom_name)

    func_node = _find_function_node(tree, atom_name)
    if func_node is None:
        logger.debug("Function %s not found in %s", atom_name, file_path)
        return DataFlowSummary(atom_id=atom_name)

    signals_in = _extract_params(func_node)
    signals_out = _extract_return_type(func_node)
    stores_touched = _extract_store_access(func_node, store_definitions, atom_name)

    return DataFlowSummary(
        atom_id=atom_name,
        signals_in=signals_in,
        signals_out=signals_out,
        stores_touched=stores_touched,
    )


def extract_all_data_flows(
    atom_registry: dict[str, dict[str, Any]],
    store_definitions: dict[str, list[str]] | None = None,
) -> dict[str, DataFlowSummary]:
    """Extract data flow summaries for all atoms.

    Args:
        atom_registry: Map of atom_name to metadata.
        store_definitions: Optional store access patterns.

    Returns:
        Dict mapping atom_name to DataFlowSummary.
    """
    summaries: dict[str, DataFlowSummary] = {}
    for atom_name, meta in atom_registry.items():
        file_path = Path(meta["file"])
        summaries[atom_name] = extract_data_flow(
            atom_name,
            file_path,
            store_definitions=store_definitions,
        )
    return summaries
