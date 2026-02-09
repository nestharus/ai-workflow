"""Classify the projection type of each architectural import of an atom."""

from __future__ import annotations

import logging
import re

from spec_manager.analysis.import_scanner import ImportHit
from spec_manager.schemas.lineage import LineageEdge
from spec_manager.schemas.pin_functions import ProjectionType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_IMPORT_RE = re.compile(r"^\s*import\s+(.+)", re.MULTILINE)
_FROM_IMPORT_RE = re.compile(r"^\s*from\s+(\S+)\s+import\s+(.+)", re.MULTILINE)

# Matches function definitions (def / async def) and captures the name.
# Use [ \t]* (not \s*) so the indent group never captures newlines.
_FUNC_DEF_RE = re.compile(r"^([ \t]*)(async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)


# ---------------------------------------------------------------------------
# Lightweight function boundary detection
# ---------------------------------------------------------------------------


def _find_functions(source: str) -> list[tuple[str, int, int]]:
    """Return (name, start_line, end_line) for each function in *source*.

    Uses indentation-based scope detection: a function ends when a line at
    the same or lesser indentation is encountered (or at EOF).
    """
    lines = source.splitlines()
    functions: list[tuple[str, int, int]] = []

    for m in _FUNC_DEF_RE.finditer(source):
        indent_level = len(m.group(1))
        name = m.group(3)
        # line numbers are 1-based
        start_line = source[: m.start()].count("\n") + 1

        # Walk forward from the line after the def to find the end.
        end_line = start_line
        for i in range(start_line, len(lines)):  # start_line is 0-indexed line after def
            line = lines[i]
            # Skip blank lines and comment-only lines
            stripped = line.strip()
            if stripped == "" or stripped.startswith("#"):
                end_line = i + 1  # 1-based
                continue
            # Measure indentation of this line
            line_indent = len(line) - len(line.lstrip())
            if line_indent > indent_level:
                end_line = i + 1  # 1-based
            else:
                # This line is at the same or lesser indentation -- function ended.
                break
        functions.append((name, start_line, end_line))

    return functions


def _get_function_body(source: str, start_line: int, end_line: int) -> str:
    """Extract the source text of a function from *start_line* to *end_line* (1-based inclusive)."""
    lines = source.splitlines()
    return "\n".join(lines[start_line - 1 : end_line])


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _count_atom_calls_in_text(
    text: str,
    atom_local_names: set[str],
) -> int:
    """Count distinct atom function calls in *text* using regex."""
    calls = set(re.findall(r"\b(\w+)\s*\(", text))
    return len(calls & atom_local_names)


def _text_returns_atom_directly(
    text: str,
    atom_local_name: str,
) -> bool:
    """Check whether *text* contains a ``return atom_func(...)`` pattern.

    A pass-through pattern looks like:
        def wrapper(...):
            return atom_func(...)
    """
    # Match "return <name>(" possibly with attribute access "return obj.<name>(".
    pattern = re.compile(
        r"\breturn\s+(?:\w+\.)*" + re.escape(atom_local_name) + r"\s*\(",
        re.MULTILINE,
    )
    return bool(pattern.search(text))


def _find_enclosing_function(
    source: str,
    target_lineno: int,
) -> tuple[str, int, int] | None:
    """Find the function definition enclosing *target_lineno*.

    Returns (name, start_line, end_line) or None.
    """
    functions = _find_functions(source)
    best: tuple[str, int, int] | None = None
    for name, start, end in functions:
        if start <= target_lineno <= end and (best is None or start > best[1]):
            best = (name, start, end)
    return best


def _get_imported_local_names(
    source: str,
    all_atom_names: set[str],
) -> dict[str, str]:
    """Map local alias -> canonical atom name for all atom imports in the file."""
    imported: dict[str, str] = {}

    for m in _FROM_IMPORT_RE.finditer(source):
        names_part = m.group(2)
        for segment in names_part.split(","):
            segment = segment.strip()
            if not segment:
                continue
            # Handle "name as alias" syntax
            parts = re.split(r"\s+as\s+", segment, maxsplit=1)
            name = parts[0].strip()
            alias = parts[1].strip() if len(parts) > 1 else name
            if name in all_atom_names:
                imported[alias] = name

    for m in _IMPORT_RE.finditer(source):
        names_part = m.group(1)
        for segment in names_part.split(","):
            segment = segment.strip()
            if not segment:
                continue
            parts = re.split(r"\s+as\s+", segment, maxsplit=1)
            full_name = parts[0].strip()
            tail = full_name.split(".")[-1]
            alias = parts[1].strip() if len(parts) > 1 else full_name
            if tail in all_atom_names:
                imported[alias] = tail

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

    # Quick syntax check -- if the source is not valid Python the regex
    # heuristics below may produce unreliable results, so bail early.
    try:
        compile(arch_source, hit.arch_file, "exec")
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
    local_names_map = _get_imported_local_names(arch_source, all_atom_names)
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

    enclosing = _find_enclosing_function(arch_source, target_lineno) if target_lineno else None

    if enclosing is not None:
        _func_name, func_start, func_end = enclosing
        func_body = _get_function_body(arch_source, func_start, func_end)

        atom_call_count = _count_atom_calls_in_text(func_body, atom_local_names)

        if atom_call_count > 1:
            transformation = ProjectionType.SMEAR
        elif _text_returns_atom_directly(func_body, hit_local_name):
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
