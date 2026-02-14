"""Step 3: Build routing table — LLM classifies source spans into destinations."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from spec_manager.core.agent_utils import run_agent
from spec_manager.intake.types import LibraryDef, ResolvedReference, RouteEntry, SourceSpan
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
- "TM MUST perform ticket status transitions under locks"
  -> DETAIL/ALGORITHM (different impl could use DB transactions)
- "blocker_kind MUST be present when status == blocked"
  -> DETAIL/SHAPE (field validation rule)
- "Steps MUST emit step_start / step_stop events"
  -> DETAIL/ALGORITHM (prescribes specific event names)
- "Trust > Friction > Performance"
  -> CONSTRAINTS (guiding principle, survives reimplementation)
- "No silent termination"
  -> CONSTRAINTS (constrains ALL algorithms regardless of impl)
- "We chose file-based queues because..."
  -> ANALYSIS (decision rationale)
- "The system processes tickets through a lifecycle"
  -> DETAIL/ALGORITHM (expressible as functions)
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


def _parse_route_entries(data: dict, source_file: str) -> list[RouteEntry]:
    """Parse JSON routing output into RouteEntry objects."""
    entries: list[RouteEntry] = []

    if "routes" not in data:
        raise ValueError(
            f"Routing JSON for {source_file} missing 'routes' key. Got keys: {sorted(data.keys())}"
        )

    for route_data in data["routes"]:
        bucket = route_data.get("bucket")
        if bucket is None:
            raise ValueError(f"Route in {source_file} missing 'bucket'. Route data: {route_data}")

        library = route_data.get("library", "")
        if not library:
            raise ValueError(
                f"Route in {source_file} missing 'library'. "
                f"Bucket={bucket}, lines {route_data.get('start')}-{route_data.get('end')}."
            )
        raw_ref_stubs = route_data.get("ref_stubs", [])
        if not isinstance(raw_ref_stubs, list):
            raise TypeError(f"Route in {source_file} has non-list 'ref_stubs': {raw_ref_stubs!r}")

        entries.append(
            RouteEntry(
                route_id="",
                src=SourceSpan(
                    file=source_file,
                    start=route_data["start"],
                    end=route_data["end"],
                ),
                library=library,
                bucket=bucket,
                element_id=route_data.get("element_id", ""),
                notes=route_data.get("notes", ""),
                ref_stubs=[str(stub) for stub in raw_ref_stubs if str(stub).strip()],
            )
        )

    return entries


_BUCKET_PREFIXES: dict[str, str] = {
    "DETAIL/ALGORITHM": "ALG",
    "DETAIL/STORE": "STO",
    "DETAIL/SHAPE": "SHP",
    "CONSTRAINTS": "CON",
    "ANALYSIS": "ANL",
}


def _reassign_element_ids(routes: list[RouteEntry]) -> None:
    """Reassign element IDs to guarantee global uniqueness.

    The LLM generates per-file counters that collide across files.
    This uses a (library, bucket) counter to produce unique IDs.
    """
    counters: dict[tuple[str, str], int] = defaultdict(int)
    for route in routes:
        if route.bucket == "IGNORED":
            continue
        prefix = _BUCKET_PREFIXES.get(route.bucket)
        if prefix is None:
            raise ValueError(
                f"Unknown bucket {route.bucket!r} in route {route.route_id} "
                f"({route.src.file}:{route.src.start}-{route.src.end}). "
                f"Valid buckets: {sorted(_BUCKET_PREFIXES.keys())}"
            )
        key = (route.library, route.bucket)
        counters[key] += 1
        route.element_id = f"{prefix}-{route.library}-{counters[key]:03d}"


def _assign_route_ids(routes: list[RouteEntry]) -> None:
    """Assign globally unique route IDs in deterministic order."""
    for idx, route in enumerate(routes, start=1):
        route.route_id = f"R-{idx:06d}"


_FILE_REF_PATTERN = re.compile(
    r"(?P<file>[A-Za-z0-9][A-Za-z0-9_./-]*\.md)"
    r"(?:(?::|#L)(?P<start>\d+)(?:[-:](?P<end>\d+))?)?",
    flags=re.IGNORECASE,
)
_LINE_HINT_PATTERN = re.compile(
    r"(?:line|lines|L)\s*(?P<start>\d+)(?:\s*[-\u2013]\s*(?P<end>\d+))?",
    flags=re.IGNORECASE,
)
_ROUTE_ID_PATTERN = re.compile(r"\bR-\d{6}\b", flags=re.IGNORECASE)
_ELEMENT_ID_PATTERN = re.compile(
    r"\b(?:ALG|STO|SHP|CON|ANL)-[A-Z0-9-]+-\d{3}\b", flags=re.IGNORECASE
)
_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "into",
    "across",
    "through",
    "when",
    "while",
    "then",
    "also",
    "only",
    "must",
    "should",
    "could",
    "would",
    "about",
    "after",
    "before",
    "during",
    "where",
    "what",
    "which",
    "under",
    "over",
    "between",
    "above",
    "below",
    "same",
    "other",
    "than",
    "onto",
    "see",
}


def _normalize_identifier(value: str) -> str:
    """Lowercase and strip non-alphanumeric characters for fuzzy matching."""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _tokenize(text: str) -> set[str]:
    """Tokenize text into stable lexical units for deterministic matching."""
    return {
        token for token in re.findall(r"[a-z0-9]{3,}", text.lower()) if token not in _STOP_WORDS
    }


def _candidate_aliases_for_file(file_path: str) -> set[str]:
    """Generate lookup aliases for a routed source file."""
    path = Path(file_path)
    aliases = {
        file_path.lower(),
        path.name.lower(),
        path.stem.lower(),
    }
    stem_tokens = [tok for tok in re.split(r"[_\-.]+", path.stem.lower()) if tok]
    if stem_tokens:
        aliases.add("_".join(stem_tokens))
        aliases.add("-".join(stem_tokens))
        aliases.add("".join(stem_tokens))
        if stem_tokens[-1] in {"service", "services", "processor", "processing", "operations"}:
            trimmed = stem_tokens[:-1]
            if trimmed:
                aliases.add("_".join(trimmed))
                aliases.add("-".join(trimmed))
                aliases.add("".join(trimmed))
        if "and" in stem_tokens:
            no_and = [tok for tok in stem_tokens if tok != "and"]
            if no_and:
                aliases.add("_".join(no_and))
                aliases.add("-".join(no_and))
                aliases.add("".join(no_and))

    expanded: set[str] = set()
    for alias in aliases:
        normalized = alias.strip().lower()
        if not normalized:
            continue
        expanded.add(normalized)
        expanded.add(_normalize_identifier(normalized))
        if normalized.endswith(".md"):
            base = normalized[:-3]
            expanded.add(base)
            expanded.add(_normalize_identifier(base))
        else:
            expanded.add(f"{normalized}.md")
            expanded.add(_normalize_identifier(f"{normalized}.md"))
    return expanded


def _extract_line_hint(stub: str) -> tuple[int, int] | None:
    """Extract an explicit line hint from a stub string if one exists."""
    file_match = _FILE_REF_PATTERN.search(stub)
    if file_match and file_match.group("start"):
        start = int(file_match.group("start"))
        end = int(file_match.group("end") or start)
        return (start, end) if end >= start else (start, start)

    line_match = _LINE_HINT_PATTERN.search(stub)
    if line_match:
        start = int(line_match.group("start"))
        end = int(line_match.group("end") or start)
        return (start, end) if end >= start else (start, start)
    return None


def _line_overlap(route: RouteEntry, line_hint: tuple[int, int]) -> bool:
    """Return whether route source span overlaps a line hint range."""
    hint_start, hint_end = line_hint
    return route.src.start <= hint_end and hint_start <= route.src.end


def _resolve_stub_file(
    stub: str,
    alias_to_files: dict[str, set[str]],
) -> str | None:
    """Resolve a stub to a specific source file path."""
    for file_match in _FILE_REF_PATTERN.finditer(stub):
        raw_ref = file_match.group("file").lower()
        for alias in (raw_ref, _normalize_identifier(raw_ref)):
            candidates = alias_to_files.get(alias, set())
            if candidates:
                return sorted(candidates)[0]

    normalized_stub = _normalize_identifier(stub)
    best_file: str | None = None
    best_alias_len = 0
    for alias, files in alias_to_files.items():
        normalized_alias = _normalize_identifier(alias)
        if len(normalized_alias) < 4:
            continue
        if normalized_alias in normalized_stub:
            candidate_file = sorted(files)[0]
            if len(normalized_alias) > best_alias_len:
                best_alias_len = len(normalized_alias)
                best_file = candidate_file
    return best_file


def _build_route_token_cache(
    routes: list[RouteEntry],
    source_dir: Path,
) -> dict[str, set[str]]:
    """Build lexical token sets for routed spans to support stub resolution."""
    source_cache: dict[str, list[str]] = {}
    token_cache: dict[str, set[str]] = {}
    for route in routes:
        tokens = _tokenize(f"{route.src.file} {route.notes}")
        if route.src.file not in source_cache:
            source_path = source_dir / route.src.file
            if source_path.exists():
                source_cache[route.src.file] = source_path.read_text(encoding="utf-8").splitlines()
            else:
                source_cache[route.src.file] = []
        lines = source_cache[route.src.file]
        if lines:
            segment = "\n".join(lines[max(0, route.src.start - 1) : route.src.end])
            tokens.update(_tokenize(segment))
        token_cache[route.route_id] = tokens
    return token_cache


def _pick_best_route_candidate(
    candidates: list[RouteEntry],
    stub_tokens: set[str],
    token_cache: dict[str, set[str]],
    line_hint: tuple[int, int] | None,
    min_score: float,
) -> RouteEntry | None:
    """Pick the best route candidate for a cross-file stub."""
    if not candidates:
        return None

    scoped = [candidate for candidate in candidates if candidate.bucket != "IGNORED"] or candidates
    if line_hint:
        overlapping = [candidate for candidate in scoped if _line_overlap(candidate, line_hint)]
        if overlapping:
            return min(
                overlapping,
                key=lambda route: (
                    abs(route.src.start - line_hint[0]),
                    route.src.end,
                    route.route_id,
                ),
            )

    if not stub_tokens:
        return scoped[0]

    scored: list[tuple[float, RouteEntry]] = []
    for candidate in scoped:
        candidate_tokens = token_cache.get(candidate.route_id, set())
        if not candidate_tokens:
            continue
        overlap = len(stub_tokens & candidate_tokens)
        if overlap == 0:
            continue
        score = overlap / len(stub_tokens)
        scored.append((score, candidate))

    if not scored:
        return None

    score, route = max(
        scored,
        key=lambda item: (
            item[0],
            -item[1].src.start,
            item[1].route_id,
        ),
    )
    return route if score >= min_score else None


def _resolve_ref_stubs(routes: list[RouteEntry], source_dir: Path) -> None:
    """Resolve cross-file stubs to concrete source spans once routing is complete."""
    if not routes:
        return

    routes_by_file: dict[str, list[RouteEntry]] = defaultdict(list)
    routes_by_route_id: dict[str, RouteEntry] = {}
    routes_by_element_id: dict[str, RouteEntry] = {}
    alias_to_files: dict[str, set[str]] = defaultdict(set)

    for route in routes:
        routes_by_file[route.src.file].append(route)
        routes_by_route_id[route.route_id.upper()] = route
        if route.element_id:
            routes_by_element_id[route.element_id.upper()] = route

    for file_path, file_routes in routes_by_file.items():
        file_routes.sort(key=lambda route: (route.src.start, route.src.end, route.route_id))
        for alias in _candidate_aliases_for_file(file_path):
            alias_to_files[alias].add(file_path)

    token_cache = _build_route_token_cache(routes, source_dir)
    resolved_count = 0
    unresolved_count = 0

    for route in routes:
        if not route.ref_stubs:
            continue

        unresolved_stubs: list[str] = []
        for stub in route.ref_stubs:
            stub_text = str(stub).strip()
            if not stub_text:
                continue

            resolved_route: RouteEntry | None = None
            route_id_match = _ROUTE_ID_PATTERN.search(stub_text)
            if route_id_match:
                resolved_route = routes_by_route_id.get(route_id_match.group(0).upper())
            if resolved_route is None:
                element_match = _ELEMENT_ID_PATTERN.search(stub_text)
                if element_match:
                    resolved_route = routes_by_element_id.get(element_match.group(0).upper())

            line_hint = _extract_line_hint(stub_text)
            if resolved_route is None:
                target_file = _resolve_stub_file(stub_text, alias_to_files)
                if target_file:
                    candidates = [
                        candidate
                        for candidate in routes_by_file.get(target_file, [])
                        if candidate.route_id != route.route_id
                    ]
                    resolved_route = _pick_best_route_candidate(
                        candidates=candidates,
                        stub_tokens=_tokenize(stub_text),
                        token_cache=token_cache,
                        line_hint=line_hint,
                        min_score=0.0,
                    )

            if resolved_route is None:
                candidates = [
                    candidate
                    for candidate in routes
                    if candidate.route_id != route.route_id and candidate.src.file != route.src.file
                ]
                resolved_route = _pick_best_route_candidate(
                    candidates=candidates,
                    stub_tokens=_tokenize(stub_text),
                    token_cache=token_cache,
                    line_hint=line_hint,
                    min_score=0.35,
                )

            if resolved_route is None:
                unresolved_stubs.append(stub_text)
                unresolved_count += 1
                continue

            route.resolved_refs.append(
                ResolvedReference(
                    stub=stub_text,
                    target=SourceSpan(
                        file=resolved_route.src.file,
                        start=resolved_route.src.start,
                        end=resolved_route.src.end,
                    ),
                    target_route_id=resolved_route.route_id,
                    target_element_id=resolved_route.element_id,
                )
            )
            resolved_count += 1

        route.ref_stubs = unresolved_stubs

    if resolved_count:
        logger.info("Resolved %d cross-file reference stubs", resolved_count)
    if unresolved_count:
        logger.warning(
            "Unable to resolve %d cross-file reference stubs after routing",
            unresolved_count,
        )


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
        "## Output Requirements\n\n"
        "Return JSON with a top-level `routes` array.\n"
        "Each route MUST include: `start`, `end`, `library`, `bucket`, "
        "`element_id`, `notes`, `ref_stubs`.\n"
        "Use one of these buckets: ANALYSIS, CONSTRAINTS, DETAIL/ALGORITHM, "
        "DETAIL/STORE, DETAIL/SHAPE, IGNORED.\n\n"
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
    summaries: list[dict],
    output_dir: Path,
) -> tuple[list[RouteEntry], list[LibraryDef]]:
    """Build a routing table mapping source spans to destinations.

    If routing fails because content doesn't fit any library, re-runs
    library discovery with feedback and retries routing for the failed
    files.

    Args:
        source_dir: Directory containing source .md files.
        libraries: Discovered library definitions from Step 2.
        summaries: Step 1 summary payloads for rediscovery feedback.
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
                entries = _route_file(source_file, source_dir, library_context, output_dir)
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

        unroutable_file_ids = [f.stem for f in failed_files]
        new_libraries = discover_libraries(
            summaries,
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
    _assign_route_ids(all_routes)
    _resolve_ref_stubs(all_routes, source_dir)

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
                    "bucket": entry.bucket,
                    "element_id": entry.element_id,
                },
                "notes": entry.notes,
                "ref_stubs": entry.ref_stubs,
                "resolved_refs": [
                    {
                        "stub": ref.stub,
                        "target": {
                            "file": ref.target.file,
                            "start": ref.target.start,
                            "end": ref.target.end,
                        },
                        "target_route_id": ref.target_route_id,
                        "target_element_id": ref.target_element_id,
                    }
                    for ref in entry.resolved_refs
                ],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info("Total routes: %d across %d files", len(all_routes), len(source_files))
    return all_routes, current_libraries
