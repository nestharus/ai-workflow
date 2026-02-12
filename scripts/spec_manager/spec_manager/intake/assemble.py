"""Step 5: Verbatim copy assembly — deterministic, no LLM calls."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from spec_manager.intake.types import LibraryDef, RouteEntry

logger = logging.getLogger(__name__)

# Map category to output file path within a library directory.
_CATEGORY_PATHS: dict[str, str] = {
    "ANALYSIS": "analysis.md",
    "CONSTRAINTS": "constraints.md",
    "DETAIL/ALGORITHM": "details/algorithms.md",
    "DETAIL/STORE": "details/stores.md",
    "DETAIL/SHAPE": "details/shapes.md",
}


def _read_source_lines(source_dir: Path, file_path: str) -> list[str]:
    """Read source file and return all lines (1-indexed access via index+1)."""
    full_path = source_dir / file_path
    if not full_path.exists():
        raise FileNotFoundError(f"Source file not found: {full_path}")
    return full_path.read_text(encoding="utf-8").splitlines()


def _extract_verbatim(source_lines: list[str], start: int, end: int) -> str:
    """Extract verbatim text for a line range (1-based inclusive)."""
    # Convert to 0-based indexing
    start_idx = max(0, start - 1)
    end_idx = min(len(source_lines), end)
    return "\n".join(source_lines[start_idx:end_idx])


def assemble_output(
    source_dir: Path,
    routes: list[RouteEntry],
    libraries: list[LibraryDef],
    output_dir: Path,
) -> Path:
    """Assemble structured output by verbatim copy from routing table.

    Args:
        source_dir: Directory containing source .md files.
        routes: Routing entries from Step 3.
        libraries: Library definitions from Step 2.
        output_dir: Root output directory.

    Returns:
        Path to the libraries output directory.
    """
    libraries_dir = output_dir / "libraries"
    libraries_dir.mkdir(parents=True, exist_ok=True)

    # Build library lookup
    lib_lookup = {lib.lib_id: lib for lib in libraries}

    # Group routes by library, then by category
    lib_cat_routes: dict[str, dict[str, list[RouteEntry]]] = defaultdict(lambda: defaultdict(list))
    for route in routes:
        if route.category == "IGNORED":
            continue
        lib_cat_routes[route.library][route.category].append(route)

    # Cache source file contents
    source_cache: dict[str, list[str]] = {}

    # Assemble system-level routes (no library) separately
    if "" in lib_cat_routes:
        sys_cat_routes = lib_cat_routes.pop("")
        sys_dir = output_dir / "system"
        sys_dir.mkdir(parents=True, exist_ok=True)

        has_details = any(cat.startswith("DETAIL/") for cat in sys_cat_routes)
        if has_details:
            (sys_dir / "details").mkdir(parents=True, exist_ok=True)

        for category in sorted(sys_cat_routes.keys()):
            output_path = _CATEGORY_PATHS.get(category)
            if not output_path:
                raise ValueError(
                    f"Unknown category {category!r} for system-level routes. "
                    f"Valid categories: {sorted(_CATEGORY_PATHS.keys())}"
                )

            cat_routes = sys_cat_routes[category]
            cat_routes.sort(key=lambda r: (r.src.file, r.src.start))

            out_file = sys_dir / output_path
            parts: list[str] = []
            cat_label = category.replace("/", " — ")
            parts.append(f"# System: {cat_label}\n")

            for route in cat_routes:
                if route.src.file not in source_cache:
                    source_cache[route.src.file] = _read_source_lines(source_dir, route.src.file)
                source_lines = source_cache[route.src.file]
                text = _extract_verbatim(source_lines, route.src.start, route.src.end)
                parts.append(f"\n([={route.element_id}])")
                parts.append(f"<!-- source: {route.src.file}:{route.src.start}-{route.src.end} -->")
                parts.append(text)
                parts.append("")

            out_file.write_text("\n".join(parts), encoding="utf-8")
            logger.info("Assembled system/%s: %d entries", output_path, len(cat_routes))

    for lib_id in sorted(lib_cat_routes.keys()):
        lib = lib_lookup.get(lib_id)
        lib_name = lib.name if lib else lib_id
        lib_dir = libraries_dir / lib_id
        lib_dir.mkdir(parents=True, exist_ok=True)

        # Create details subdirectory if needed
        has_details = any(cat.startswith("DETAIL/") for cat in lib_cat_routes[lib_id])
        if has_details:
            (lib_dir / "details").mkdir(parents=True, exist_ok=True)

        for category in sorted(lib_cat_routes[lib_id].keys()):
            output_path = _CATEGORY_PATHS.get(category)
            if not output_path:
                raise ValueError(
                    f"Unknown category {category!r} for library {lib_id}. "
                    f"Valid categories: {sorted(_CATEGORY_PATHS.keys())}"
                )

            cat_routes = lib_cat_routes[lib_id][category]
            # Sort by source file then start line for deterministic output
            cat_routes.sort(key=lambda r: (r.src.file, r.src.start))

            out_file = lib_dir / output_path
            parts: list[str] = []

            # Header
            cat_label = category.replace("/", " — ")
            parts.append(f"# {lib_name}: {cat_label}\n")

            for route in cat_routes:
                # Get source lines (cached)
                if route.src.file not in source_cache:
                    source_cache[route.src.file] = _read_source_lines(source_dir, route.src.file)
                source_lines = source_cache[route.src.file]

                # Extract verbatim text
                text = _extract_verbatim(source_lines, route.src.start, route.src.end)

                # Add element annotation and content
                parts.append(f"\n([={route.element_id}])")
                parts.append(f"<!-- source: {route.src.file}:{route.src.start}-{route.src.end} -->")
                parts.append(text)
                parts.append("")  # blank line separator

            out_file.write_text("\n".join(parts), encoding="utf-8")
            logger.info(
                "Assembled %s/%s: %d entries",
                lib_id,
                output_path,
                len(cat_routes),
            )

    # Write constraints_index.json for each library that has CONSTRAINTS routes
    _write_constraints_indexes(source_cache, source_dir, routes, libraries_dir)

    logger.info(
        "Assembly complete: %d libraries in %s",
        len(lib_cat_routes),
        libraries_dir,
    )
    return libraries_dir


def _write_constraints_indexes(
    source_cache: dict[str, list[str]],
    source_dir: Path,
    routes: list[RouteEntry],
    libraries_dir: Path,
) -> None:
    """Write constraints_index.json per library with subtype tags.

    For each library that has CONSTRAINTS-category routes, classifies each
    constraint element and writes a JSON index file alongside constraints.md.
    """
    from spec_manager.planner.constraints.bootstrap import _classify_constraint_subtype

    # Group CONSTRAINTS routes by library
    lib_constraint_routes: dict[str, list[RouteEntry]] = defaultdict(list)
    for route in routes:
        if route.category == "CONSTRAINTS":
            lib_constraint_routes[route.library].append(route)

    for lib_id, constraint_routes in lib_constraint_routes.items():
        if not lib_id:
            continue  # Skip system-level for now

        entries: list[dict[str, str | list[str]]] = []
        for route in constraint_routes:
            if route.src.file not in source_cache:
                try:
                    source_cache[route.src.file] = _read_source_lines(source_dir, route.src.file)
                except FileNotFoundError:
                    continue
            source_lines = source_cache[route.src.file]
            text = _extract_verbatim(source_lines, route.src.start, route.src.end)
            entry = _classify_constraint_subtype(route.element_id, text)
            entries.append(
                {
                    "element_id": entry.element_id,
                    "subtype": entry.subtype,
                    "scope_hint": entry.scope_hint,
                    "entities": entry.entities,
                    "text_preview": entry.text_preview,
                }
            )

        if entries:
            lib_dir = libraries_dir / lib_id
            lib_dir.mkdir(parents=True, exist_ok=True)
            index_path = lib_dir / "constraints_index.json"
            index_path.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(
                "Wrote constraints_index.json for %s: %d entries",
                lib_id,
                len(entries),
            )
