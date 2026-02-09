"""Extract data flow summaries (signals in/out, stores touched) per atom."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import RawFunctionInfo, SourceAnalysis, analyze_source
from spec_manager.schemas.lineage import DataFlowSummary

logger = logging.getLogger(__name__)

_STORE_KEYWORDS = {"store", "cache", "db", "database", "repository", "repo", "registry"}
_STORE_ACCESS_RE = re.compile(r"\b(\w+)\.(\w+)")


def _find_function(
    analysis: SourceAnalysis,
    func_name: str,
) -> RawFunctionInfo | None:
    """Locate the RawFunctionInfo for a function by name."""
    for func in analysis.functions:
        if func.name == func_name:
            return func
    return None


def _extract_params(
    func: RawFunctionInfo,
    source_lines: list[str],
) -> list[str]:
    """Extract parameter names with optional type annotations from source text.

    Uses the function's start_line to locate the ``def`` signature in source,
    then parses parameter names and annotations from the raw text.
    """
    # Build the full signature text by joining lines from def until we find
    # the closing ')'.  Handles multi-line signatures.
    sig_lines: list[str] = []
    for i in range(func.start_line - 1, min(func.end_line, len(source_lines))):
        sig_lines.append(source_lines[i])
        if ")" in source_lines[i]:
            break

    sig_text = " ".join(sig_lines)

    # Extract everything between the first '(' and the matching ')'.
    paren_match = re.search(r"\(([^)]*)\)", sig_text)
    if not paren_match:
        return list(func.args)

    params_text = paren_match.group(1)

    params: list[str] = []
    for part in params_text.split(","):
        part = part.strip()
        if not part or part == "self" or part == "cls":
            continue
        # Remove default value (everything after '=')
        if "=" in part:
            part = part[: part.index("=")].rstrip()
        # Keep "name: annotation" or just "name"
        params.append(part)

    return params


def _extract_return_type(func: RawFunctionInfo) -> list[str]:
    """Extract return type annotation if present."""
    if func.return_annotation:
        return [func.return_annotation]
    return []


def _extract_store_access(
    func: RawFunctionInfo,
    source_lines: list[str],
    store_definitions: dict[str, list[str]] | None,
    atom_name: str,
) -> list[str]:
    """Detect store identifiers accessed by the function.

    Uses two strategies:
    1. If *store_definitions* maps store_id -> [atom_ids], look up which
       stores list this atom.
    2. Heuristic: scan for attribute access patterns that resemble store
       operations (e.g., ``self.store``, ``db.get``, ``cache.set``).
    """
    stores: set[str] = set()

    # Strategy 1: explicit store definitions.
    if store_definitions:
        for store_id, atom_ids in store_definitions.items():
            if atom_name in atom_ids:
                stores.add(store_id)

    # Strategy 2: heuristic detection from attribute access in function body.
    body_start = func.start_line - 1
    body_end = min(func.end_line, len(source_lines))
    for i in range(body_start, body_end):
        line = source_lines[i]
        for match in _STORE_ACCESS_RE.finditer(line):
            obj_name = match.group(1)
            attr_name = match.group(2)
            if obj_name.lower() in _STORE_KEYWORDS:
                stores.add(f"{obj_name}.{attr_name}")

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

    analysis = analyze_source(source, filepath=str(file_path))
    source_lines = source.splitlines()

    func = _find_function(analysis, atom_name)
    if func is None:
        logger.debug("Function %s not found in %s", atom_name, file_path)
        return DataFlowSummary(atom_id=atom_name)

    signals_in = _extract_params(func, source_lines)
    signals_out = _extract_return_type(func)
    stores_touched = _extract_store_access(func, source_lines, store_definitions, atom_name)

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
