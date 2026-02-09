"""Scan architectural source files for imports of algorithmic atom functions."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import SourceAnalysis, analyze_source

logger = logging.getLogger(__name__)

# Regex patterns for import detection
_IMPORT_RE = re.compile(r"^\s*import\s+(.+)", re.MULTILINE)
_FROM_IMPORT_RE = re.compile(r"^\s*from\s+(\S+)\s+import\s+(.+)", re.MULTILINE)

# Pattern to find identifier usage (word boundary match)
_IDENT_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _ident_pattern(name: str) -> re.Pattern[str]:
    """Return a compiled pattern that matches *name* as a whole identifier."""
    if name not in _IDENT_RE_CACHE:
        _IDENT_RE_CACHE[name] = re.compile(r"(?<![.\w])" + re.escape(name) + r"(?!\w)")
    return _IDENT_RE_CACHE[name]


@dataclass
class ImportHit:
    """A detected import of an atom function in an architectural file."""

    atom_name: str
    arch_file: str
    arch_location: str  # file:class.method or file:function
    import_statement: str  # The raw import line
    usage_sites: list[str] = field(default_factory=list)  # line numbers where used


def _extract_imported_atom_names(
    source: str,
    atom_names: set[str],
) -> dict[str, str]:
    """Extract atom names imported via ``from ... import ...`` or ``import ...``.

    Returns a mapping from the local alias used in the file to the canonical
    atom name so that usage-site detection works regardless of aliasing.
    """
    imported: dict[str, str] = {}

    # Handle ``from module import name [as alias], ...``
    for match in _FROM_IMPORT_RE.finditer(source):
        names_str = match.group(2)
        # Split on commas to handle ``from x import a, b, c``
        for part in names_str.split(","):
            part = part.strip()
            if not part:
                continue
            # Handle ``name as alias``
            as_match = re.match(r"(\w+)\s+as\s+(\w+)", part)
            if as_match:
                canonical = as_match.group(1)
                local_name = as_match.group(2)
            else:
                # Could be just an identifier, or could have trailing stuff
                ident_match = re.match(r"(\w+)", part)
                if not ident_match:
                    continue
                canonical = ident_match.group(1)
                local_name = canonical
            if canonical in atom_names:
                imported[local_name] = canonical

    # Handle ``import module.path [as alias]``
    for match in _IMPORT_RE.finditer(source):
        line_text = match.group(0).strip()
        # Skip lines that are actually ``from ... import ...`` (already handled)
        if line_text.startswith("from "):
            continue
        names_str = match.group(1)
        for part in names_str.split(","):
            part = part.strip()
            if not part:
                continue
            as_match = re.match(r"([\w.]+)\s+as\s+(\w+)", part)
            if as_match:
                module_path = as_match.group(1)
                local_name = as_match.group(2)
            else:
                ident_match = re.match(r"([\w.]+)", part)
                if not ident_match:
                    continue
                module_path = ident_match.group(1)
                local_name = module_path
            # Check the final dotted component
            tail = module_path.split(".")[-1]
            if tail in atom_names:
                imported[local_name] = tail

    return imported


def _collect_usage_sites(
    source_lines: list[str],
    local_names: set[str],
) -> list[str]:
    """Collect line numbers where any of *local_names* is referenced.

    Skips import lines themselves to only report actual usage.
    """
    sites: list[str] = []
    for lineno_0, line in enumerate(source_lines):
        stripped = line.strip()
        # Skip import lines
        if stripped.startswith("import ") or stripped.startswith("from "):
            continue
        for name in local_names:
            if _ident_pattern(name).search(line):
                sites.append(str(lineno_0 + 1))
                break  # Only count each line once
    return sites


def _find_import_line_text(
    source_lines: list[str],
    canonical_name: str,
    local_name: str,
) -> str:
    """Find the raw import line that imports *canonical_name* (or its alias)."""
    for line in source_lines:
        stripped = line.strip()
        if not (stripped.startswith("import ") or stripped.startswith("from ")):
            continue
        if canonical_name in stripped or (local_name != canonical_name and local_name in stripped):
            return stripped
    return ""


def _enclosing_scope(
    analysis: SourceAnalysis,
    lineno: int,
    file_path_str: str,
) -> str:
    """Return the enclosing class.method or function name for *lineno*."""
    best: str = file_path_str
    for func in analysis.functions:
        if func.start_line <= lineno <= func.end_line:
            # Use qualified_name if it contains a dot (class.method)
            candidate = f"{file_path_str}:{func.qualified_name}"
            if len(candidate) > len(best):
                best = candidate
    return best


def scan_file_imports(
    file_path: Path,
    atom_names: set[str],
) -> list[ImportHit]:
    """Scan a single Python file for imports of known atom functions.

    Uses regex to detect:
    - ``from atoms.module import atom_func``
    - ``import atoms.module`` (checks tail of dotted module name)
    - Aliased imports via ``as``

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

    source_lines = source.splitlines()
    file_str = str(file_path)

    imported = _extract_imported_atom_names(source, atom_names)
    if not imported:
        return []

    # Lazily compute analysis only if we need enclosing scope
    _analysis: SourceAnalysis | None = None

    def get_analysis() -> SourceAnalysis:
        nonlocal _analysis
        if _analysis is None:
            _analysis = analyze_source(source, filepath=file_str)
        return _analysis

    hits: list[ImportHit] = []
    for local_name, canonical_name in imported.items():
        usage_sites = _collect_usage_sites(source_lines, {local_name})

        import_text = _find_import_line_text(source_lines, canonical_name, local_name)

        # Determine the primary usage location
        if usage_sites:
            first_lineno = int(usage_sites[0]) if usage_sites[0].isdigit() else 0
            arch_location = _enclosing_scope(get_analysis(), first_lineno, file_str)
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

    Uses ``analyze_source()`` to extract:
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

        source_lines = source.splitlines()
        analysis = analyze_source(source, filepath=str(py_file))

        for func in analysis.functions:
            # Skip private/dunder helpers
            if func.name.startswith("_"):
                continue

            # Build params list from the args tuple and source text
            params = _extract_params_from_source(source_lines, func.start_line, func.args)

            return_type = func.return_annotation or ""

            registry[func.name] = {
                "file": str(py_file),
                "line": func.start_line,
                "params": params,
                "return_type": return_type,
            }

    return registry


def _extract_params_from_source(
    source_lines: list[str],
    start_line: int,
    args: tuple[str, ...],
) -> list[str]:
    """Extract parameter strings with type annotations from source.

    Uses the function's args tuple from analyze_source. If args already
    contain type annotations (e.g. ``"amount: float"``), returns them
    directly. Otherwise, extracts params with annotations from the def
    line in the source text.
    """
    # Check if args already include type annotations
    filtered_args = [
        a.strip() for a in args if a.strip() != "self" and not a.strip().startswith("self:")
    ]
    has_annotations = any(":" in a for a in filtered_args)

    if filtered_args and has_annotations:
        params: list[str] = []
        for arg in filtered_args:
            if "=" in arg:
                arg = arg.split("=")[0].strip()
            params.append(arg)
        return params

    # Extract from source line to get type annotations
    if 0 < start_line <= len(source_lines):
        # Collect the full def line (may span multiple lines)
        def_text = source_lines[start_line - 1]
        # If the def line doesn't contain a closing paren, gather continuation
        idx = start_line
        while ")" not in def_text and idx < len(source_lines):
            def_text += " " + source_lines[idx].strip()
            idx += 1

        paren_match = re.search(r"def\s+\w+\s*\((.+?)\)", def_text)
        if paren_match:
            raw_params = paren_match.group(1)
            params = []
            for p in raw_params.split(","):
                p = p.strip()
                if p and p != "self" and not p.startswith("self:"):
                    if "=" in p:
                        p = p.split("=")[0].strip()
                    params.append(p)
            return params

    # Last resort: return plain arg names from analyze_source
    return filtered_args
