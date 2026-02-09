"""Step 3: Build routing table — LLM classifies source spans into destinations."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from spec_manager.core.agent_utils import run_agent
from spec_manager.intake.types import LibraryDef, RouteEntry, SourceSpan
from spec_manager.refinement.formats import _strip_code_fences

logger = logging.getLogger(__name__)

# Classification guidance embedded in the routing prompt.
# This is from 00_CLASSIFICATION.md and CONSOLIDATION_CONCLUSIONS.md.
_CLASSIFICATION_GUIDANCE = """\
## Classification Rules

### The Reimplementation Test
For EVERY span, ask: "Does this statement survive if you completely change
the implementation?"
- If YES and it states a general guarantee or principle -> CONSTRAINTS
- If NO -> it's a DETAIL (algorithm, store, or shape)

### The Invariant Trap (95% of "MUST" is NOT a constraint)
In real specs, the breakdown of "MUST" statements is approximately:
- ~60% algorithm steps (procedures, sequences, "do X then Y")
- ~30% shape details (field validations, schema rules, type constraints)
- ~5% true invariants/constraints (survive reimplementation)
- ~5% analysis (tradeoff reasoning, decision rationale)

Most "MUST" statements are algorithms, NOT constraints.

### When Unsure Between Constraint and Algorithm
Ask: "Could I achieve the same GOAL with a completely different approach?"
- If YES -> the statement describes ONE approach (DETAIL/ALGORITHM)
- If NO -> it describes the goal itself (CONSTRAINTS)

### Classification Examples
| Statement | Category | Why |
|-----------|----------|-----|
| "TM MUST perform ticket status transitions under locks/ticket.<id>.lock" | DETAIL/ALGORITHM | Different impl could use DB transactions |
| "blocker_kind MUST be present when status == blocked" | DETAIL/SHAPE | Field validation rule |
| "Steps MUST emit step_start / step_stop events" | DETAIL/ALGORITHM | Prescribes specific event names |
| "Trust > Friction > Performance" | CONSTRAINTS | Guiding principle, survives reimplementation |
| "No silent termination" | CONSTRAINTS | Constrains ALL algorithms regardless of impl |
| "We chose file-based queues because..." | ANALYSIS | Decision rationale |
| "The system processes tickets through a lifecycle" | DETAIL/ALGORITHM | Describes system behavior (expressible as functions) |
"""


def _build_numbered_content(file_path: Path) -> tuple[str, int]:
    """Read a file and return its content with line numbers."""
    lines = file_path.read_text(encoding="utf-8").splitlines()
    numbered = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))
    return numbered, len(lines)


def _build_library_context(libraries: list[LibraryDef]) -> str:
    """Format library definitions for inclusion in the routing prompt."""
    parts = ["## Available Libraries\n"]
    for lib in libraries:
        parts.append(f"- **{lib.lib_id}**: {lib.name} — {lib.description}")
    return "\n".join(parts)


def _parse_route_entries(
    data: dict, source_file: str
) -> list[RouteEntry]:
    """Parse JSON routing output into RouteEntry objects."""
    entries: list[RouteEntry] = []
    route_counter = len(entries)

    if "routes" not in data:
        raise ValueError(
            f"Routing JSON for {source_file} missing 'routes' key. "
            f"Got keys: {sorted(data.keys())}"
        )

    for route_data in data["routes"]:
        category = route_data.get("category")
        if category is None:
            raise ValueError(
                f"Route in {source_file} missing 'category'. "
                f"Route data: {route_data}"
            )

        route_counter += 1
        route_id = f"R-{route_counter:06d}"

        library = route_data.get("library", "")
        if category not in ("IGNORED", "CONSTRAINTS") and not library:
            raise ValueError(
                f"Non-IGNORED, non-CONSTRAINTS route in {source_file} missing 'library'. "
                f"Category={category}, lines {route_data.get('start')}-{route_data.get('end')}. "
                f"This likely means library discovery missed an orchestration library."
            )

        entries.append(
            RouteEntry(
                route_id=route_id,
                src=SourceSpan(
                    file=source_file,
                    start=route_data["start"],
                    end=route_data["end"],
                ),
                library=library,
                category=category,
                element_id=route_data.get("element_id", ""),
                notes=route_data.get("notes", ""),
                ref_stubs=route_data.get("ref_stubs", []),
            )
        )

    return entries


_CATEGORY_PREFIXES: dict[str, str] = {
    "DETAIL/ALGORITHM": "ALG",
    "DETAIL/STORE": "STO",
    "DETAIL/SHAPE": "SHP",
    "CONSTRAINTS": "CON",
    "ANALYSIS": "ANL",
}


def _reassign_element_ids(routes: list[RouteEntry]) -> None:
    """Reassign element IDs to guarantee global uniqueness.

    The LLM generates per-file counters that collide across files.
    This uses a (library, category) counter to produce unique IDs.
    """
    counters: dict[tuple[str, str], int] = defaultdict(int)
    for route in routes:
        if route.category == "IGNORED":
            continue
        prefix = _CATEGORY_PREFIXES.get(route.category)
        if prefix is None:
            raise ValueError(
                f"Unknown category {route.category!r} in route {route.route_id} "
                f"({route.src.file}:{route.src.start}-{route.src.end}). "
                f"Valid categories: {sorted(_CATEGORY_PREFIXES.keys())}"
            )
        lib_label = route.library if route.library else "SYS"
        key = (lib_label, route.category)
        counters[key] += 1
        route.element_id = f"{prefix}-{lib_label}-{counters[key]:03d}"


def _route_file(
    source_file: Path,
    source_dir: Path,
    library_context: str,
    output_dir: Path,
) -> list[RouteEntry]:
    """Route a single source file. Returns RouteEntry list."""
    numbered_content, total_lines = _build_numbered_content(source_file)

    if total_lines == 0:
        logger.warning("Skipping empty file: %s", source_file.name)
        return []

    prompt = (
        f"{_CLASSIFICATION_GUIDANCE}\n\n"
        f"{library_context}\n\n"
        "## INPUT DATA\n\n"
        f"File: {source_file.relative_to(source_dir)}\n"
        f"Total lines: {total_lines}\n\n"
        f"{numbered_content}"
    )

    last_json_error: json.JSONDecodeError | None = None
    for attempt in range(3):
        raw_output = run_agent(
            agent_name="spec-intake-route",
            prompt=prompt,
            workspace=output_dir,
        )

        cleaned = _strip_code_fences(raw_output)
        try:
            data = json.loads(cleaned)
            break
        except json.JSONDecodeError as e:
            last_json_error = e
            logger.warning(
                "JSON parse attempt %d/3 failed for %s: %s",
                attempt + 1,
                source_file.name,
                cleaned[:200],
            )
    else:
        raise ValueError(
            f"Failed to parse routing JSON for {source_file.name} "
            f"after 3 attempts: {last_json_error}"
        )

    rel_path = str(source_file.relative_to(source_dir))
    entries = _parse_route_entries(data, rel_path)
    logger.info(
        "Routed %s: %d entries (%d lines)",
        source_file.name,
        len(entries),
        total_lines,
    )
    return entries


_MAX_REDISCOVERY_ROUNDS = 2


def route_sources(
    source_dir: Path,
    libraries: list[LibraryDef],
    output_dir: Path,
) -> tuple[list[RouteEntry], list[LibraryDef]]:
    """Build a routing table mapping source spans to destinations.

    If routing fails because content doesn't fit any library, re-runs
    library discovery with feedback and retries routing for the failed
    files.

    Args:
        source_dir: Directory containing source .md files.
        libraries: Discovered library definitions from Step 2.
        output_dir: Directory for writing output artifacts.

    Returns:
        Tuple of (all RouteEntry objects, final library list including
        any libraries added during rediscovery).
    """
    from spec_manager.intake.discover import discover_libraries

    source_files = sorted(source_dir.glob("**/*.md"))
    if not source_files:
        logger.warning("No .md files found in %s", source_dir)
        return [], libraries

    current_libraries = list(libraries)
    all_routes: list[RouteEntry] = []
    pending_files = list(source_files)

    for rediscovery_round in range(_MAX_REDISCOVERY_ROUNDS + 1):
        library_context = _build_library_context(current_libraries)
        failed_files: list[Path] = []
        failed_errors: list[str] = []

        for source_file in pending_files:
            logger.info("Routing %s", source_file.name)
            try:
                entries = _route_file(
                    source_file, source_dir, library_context, output_dir
                )
                all_routes.extend(entries)
            except ValueError as e:
                error_msg = str(e)
                if "missing 'library'" in error_msg:
                    failed_files.append(source_file)
                    failed_errors.append(error_msg)
                    logger.warning(
                        "Routing %s failed (missing library): %s",
                        source_file.name,
                        error_msg,
                    )
                else:
                    raise

        if not failed_files:
            break

        if rediscovery_round >= _MAX_REDISCOVERY_ROUNDS:
            raise ValueError(
                f"Routing failed for {len(failed_files)} files after "
                f"{_MAX_REDISCOVERY_ROUNDS} rediscovery rounds. "
                f"Files: {[f.name for f in failed_files]}. "
                f"Errors: {failed_errors}"
            )

        # Re-run discovery with feedback about what's missing
        logger.info(
            "Rediscovery round %d: %d files need new libraries",
            rediscovery_round + 1,
            len(failed_files),
        )

        # Load all step-1 summaries for rediscovery
        existing_summaries: list[dict] = []
        summaries_dir = output_dir / "summaries"
        if summaries_dir.exists():
            for f in sorted(summaries_dir.glob("*.json")):
                existing_summaries.append(
                    json.loads(f.read_text(encoding="utf-8"))
                )

        unroutable_file_ids = [f.stem for f in failed_files]
        new_libraries = discover_libraries(
            existing_summaries,
            output_dir,
            existing_libraries=current_libraries,
            unroutable_files=unroutable_file_ids,
        )

        # Check if discovery actually found new libraries
        existing_ids = {lib.lib_id for lib in current_libraries}
        added = [lib for lib in new_libraries if lib.lib_id not in existing_ids]
        if not added:
            raise ValueError(
                f"Rediscovery round {rediscovery_round + 1} did not produce "
                f"new libraries. Cannot route files: "
                f"{[f.name for f in failed_files]}"
            )

        logger.info(
            "Rediscovery added %d libraries: %s",
            len(added),
            ", ".join(f"{lib.lib_id} ({lib.name})" for lib in added),
        )
        current_libraries = new_libraries
        pending_files = failed_files

    # Reassign element IDs to guarantee global uniqueness.
    _reassign_element_ids(all_routes)

    # Write route table as JSONL
    route_table_path = output_dir / "route_table.jsonl"
    with route_table_path.open("w", encoding="utf-8") as f:
        for entry in all_routes:
            record = {
                "route_id": entry.route_id,
                "src": {
                    "file": entry.src.file,
                    "start": entry.src.start,
                    "end": entry.src.end,
                },
                "dest": {
                    "library": entry.library,
                    "category": entry.category,
                    "element_id": entry.element_id,
                },
                "notes": entry.notes,
                "ref_stubs": entry.ref_stubs,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info("Total routes: %d across %d files", len(all_routes), len(source_files))
    return all_routes, current_libraries
