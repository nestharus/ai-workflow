"""Step 5: Verbatim copy assembly — deterministic, no LLM calls."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from spec_manager.intake.types import LibraryDef, RouteEntry

logger = logging.getLogger(__name__)

# Map bucket to output file path within a library directory.
_BUCKET_PATHS: dict[str, str] = {
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

    # Group routes by library, then by bucket.
    lib_bucket_routes: dict[str, dict[str, list[RouteEntry]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for route in routes:
        if route.bucket == "IGNORED":
            continue
        if not route.library:
            raise ValueError(
                f"Route {route.route_id} has empty library for "
                f"{route.src.file}:{route.src.start}-{route.src.end}"
            )
        lib_bucket_routes[route.library][route.bucket].append(route)

    # Cache source file contents
    source_cache: dict[str, list[str]] = {}

    for lib_id in sorted(lib_bucket_routes.keys()):
        lib = lib_lookup.get(lib_id)
        lib_name = lib.name if lib else lib_id
        lib_dir = libraries_dir / lib_id
        lib_dir.mkdir(parents=True, exist_ok=True)

        # Create details subdirectory if needed
        has_details = any(bucket.startswith("DETAIL/") for bucket in lib_bucket_routes[lib_id])
        if has_details:
            (lib_dir / "details").mkdir(parents=True, exist_ok=True)

        for bucket in sorted(lib_bucket_routes[lib_id].keys()):
            output_path = _BUCKET_PATHS.get(bucket)
            if not output_path:
                raise ValueError(
                    f"Unknown bucket {bucket!r} for library {lib_id}. "
                    f"Valid buckets: {sorted(_BUCKET_PATHS.keys())}"
                )

            cat_routes = lib_bucket_routes[lib_id][bucket]
            # Sort by source file then start line for deterministic output
            cat_routes.sort(key=lambda r: (r.src.file, r.src.start))

            out_file = lib_dir / output_path
            parts: list[str] = []

            # Header
            cat_label = bucket.replace("/", " — ")
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
        len(lib_bucket_routes),
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

    For each library that has CONSTRAINTS bucket routes, classifies each
    constraint element and writes a JSON index file alongside constraints.md.
    """
    from spec_manager.planner.constraints.bootstrap import classify_constraint_subtype

    # Group CONSTRAINTS routes by library
    lib_constraint_routes: dict[str, list[RouteEntry]] = defaultdict(list)
    for route in routes:
        if route.bucket == "CONSTRAINTS":
            lib_constraint_routes[route.library].append(route)

    entries_by_library: dict[str, list[dict[str, str | list[str]]]] = {}
    missing_sources: list[dict[str, str | int]] = []

    for lib_id, constraint_routes in lib_constraint_routes.items():
        entries: list[dict[str, str | list[str]]] = []
        for route in constraint_routes:
            if route.src.file not in source_cache:
                try:
                    source_cache[route.src.file] = _read_source_lines(source_dir, route.src.file)
                except FileNotFoundError:
                    missing_sources.append(
                        {
                            "library": lib_id,
                            "route_id": route.route_id,
                            "source_file": route.src.file,
                            "start": route.src.start,
                            "end": route.src.end,
                        }
                    )
                    continue
            source_lines = source_cache[route.src.file]
            text = _extract_verbatim(source_lines, route.src.start, route.src.end)
            entry = classify_constraint_subtype(route.element_id, text)
            entries.append(
                {
                    "element_id": entry.element_id,
                    "subtype": entry.subtype,
                    "scope_hint": entry.scope_hint,
                    "entities": entry.entities,
                    "text_preview": entry.text_preview,
                }
            )
        entries_by_library[lib_id] = entries

    if missing_sources:
        missing_details = ", ".join(
            (
                f"{item['library']}:{item['route_id']} "
                f"{item['source_file']}:{item['start']}-{item['end']}"
            )
            for item in missing_sources
        )
        raise FileNotFoundError(
            "Missing source files while building constraints indexes. "
            f"Run is incomplete. Missing routes: {missing_details}"
        )

    for lib_id, entries in entries_by_library.items():
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
