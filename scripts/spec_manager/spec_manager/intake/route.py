"""Step 3: Build routing table — LLM classifies source spans into destinations."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from spec_manager.core.agent_utils import run_agent
from spec_manager.intake.types import (
    INTAKE_MODE_INTENT,
    INTAKE_MODE_PROSE,
    IntakeMode,
    LibraryDef,
    ResolvedReference,
    RouteEntry,
    SourceSpan,
    UnresolvedReference,
    normalize_intake_mode,
)
from spec_manager.refinement.formats import _strip_code_fences

logger = logging.getLogger(__name__)


class RouteParseError(ValueError):
    """Structured routing parse error for stable control flow decisions."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        source_file: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.source_file = source_file


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

_INTENT_DESTINATIONS = (
    "system/workflows",
    "system/entities",
    "system/interfaces",
)


def _build_numbered_content(file_path: Path) -> tuple[str, int]:
    """Read a file and return its content with line numbers."""
    lines = file_path.read_text(encoding="utf-8").splitlines()
    numbered = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))
    return numbered, len(lines)


def _build_destination_context(
    libraries: list[LibraryDef],
    *,
    intake_mode: IntakeMode,
) -> str:
    """Format valid routing destinations for inclusion in the prompt."""
    if intake_mode == INTAKE_MODE_INTENT:
        return (
            "## Available Destinations\n\n"
            "Intent intake is pre-decomposition. Route each span to one of:\n"
            "- system/workflows\n"
            "- system/entities\n"
            "- system/interfaces\n"
        )

    parts = ["## Available Libraries\n"]
    for lib in libraries:
        parts.append(f"- **{lib.lib_id}**: {lib.name} — {lib.description}")
    return "\n".join(parts)


def _parse_route_entries(
    data: dict,
    source_file: str,
    *,
    intake_mode: IntakeMode,
    total_lines: int,
) -> list[RouteEntry]:
    """Parse JSON routing output into RouteEntry objects."""
    entries: list[RouteEntry] = []

    if "routes" not in data:
        raise RouteParseError(
            f"Routing JSON for {source_file} missing 'routes' key. Got keys: {sorted(data.keys())}",
            code="missing_routes_array",
            source_file=source_file,
        )
    if not isinstance(data["routes"], list):
        raise RouteParseError(
            f"Routing JSON for {source_file} has non-list 'routes': "
            f"{type(data['routes']).__name__}",
            code="invalid_routes_array",
            source_file=source_file,
        )

    for route_data in data["routes"]:
        bucket = route_data.get("bucket")
        if bucket is None:
            raise RouteParseError(
                f"Route in {source_file} missing 'bucket'. Route data: {route_data}",
                code="missing_bucket",
                source_file=source_file,
            )

        raw_library = str(route_data.get("library", "")).strip()
        raw_destination = str(route_data.get("destination", "")).strip()
        destination = raw_destination or raw_library
        if not destination:
            expected_field = "destination" if intake_mode == INTAKE_MODE_INTENT else "library"
            raise RouteParseError(
                f"Route in {source_file} missing '{expected_field}'. "
                f"Bucket={bucket}, lines {route_data.get('start')}-{route_data.get('end')}.",
                code="missing_destination",
                source_file=source_file,
            )
        if intake_mode == INTAKE_MODE_INTENT and destination not in _INTENT_DESTINATIONS:
            raise RouteParseError(
                f"Route in {source_file} has invalid destination {destination!r}. "
                f"Expected one of: {_INTENT_DESTINATIONS}",
                code="invalid_destination",
                source_file=source_file,
            )
        try:
            start = int(route_data["start"])
            end = int(route_data["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RouteParseError(
                f"Route in {source_file} has invalid span fields start/end: {route_data!r}",
                code="invalid_source_span",
                source_file=source_file,
            ) from exc
        if start < 1 or end < start or end > total_lines:
            raise RouteParseError(
                f"Route in {source_file} has out-of-bounds span {start}-{end} "
                f"for file with {total_lines} lines.",
                code="invalid_source_span",
                source_file=source_file,
            )
        raw_ref_stubs = route_data.get("ref_stubs", [])
        if not isinstance(raw_ref_stubs, list):
            raise RouteParseError(
                f"Route in {source_file} has non-list 'ref_stubs': {raw_ref_stubs!r}",
                code="invalid_ref_stubs",
                source_file=source_file,
            )

        entries.append(
            RouteEntry(
                route_id="",
                src=SourceSpan(
                    file=source_file,
                    start=start,
                    end=end,
                ),
                library=destination,
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


def _destination_token(destination: str) -> str:
    """Normalize a destination string into a stable token for element IDs."""
    token = re.sub(r"[^A-Za-z0-9]+", "-", destination).strip("-").upper()
    return token or "DEST"


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
        route.element_id = f"{prefix}-{_destination_token(route.library)}-{counters[key]:03d}"


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
) -> tuple[str | None, str]:
    """Resolve a stub to a specific source file path."""
    for file_match in _FILE_REF_PATTERN.finditer(stub):
        raw_ref = file_match.group("file").lower()
        for alias in (raw_ref, _normalize_identifier(raw_ref)):
            candidates = sorted(alias_to_files.get(alias, set()))
            if len(candidates) == 1:
                return candidates[0], ""
            if len(candidates) > 1:
                return None, (f"ambiguous_file_reference:{raw_ref}:{','.join(candidates)}")

    normalized_stub = _normalize_identifier(stub)
    best_files: set[str] = set()
    best_alias_len = 0
    for alias, files in alias_to_files.items():
        normalized_alias = _normalize_identifier(alias)
        if len(normalized_alias) < 4:
            continue
        if normalized_alias in normalized_stub:
            alias_candidates = set(files)
            if len(normalized_alias) > best_alias_len:
                best_alias_len = len(normalized_alias)
                best_files = alias_candidates
            elif len(normalized_alias) == best_alias_len:
                best_files.update(alias_candidates)

    if len(best_files) == 1:
        return next(iter(best_files)), ""
    if len(best_files) > 1:
        return None, f"ambiguous_alias_match:{','.join(sorted(best_files))}"
    return None, "no_file_match"


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
) -> tuple[RouteEntry | None, str]:
    """Pick the best route candidate for a cross-file stub."""
    if not candidates:
        return None, "no_candidates"

    scoped = [candidate for candidate in candidates if candidate.bucket != "IGNORED"] or candidates
    if line_hint:
        overlapping = [candidate for candidate in scoped if _line_overlap(candidate, line_hint)]
        if len(overlapping) == 1:
            return overlapping[0], ""
        if len(overlapping) > 1:
            ranked = sorted(
                overlapping,
                key=lambda route: (
                    abs(route.src.start - line_hint[0]),
                    route.src.end,
                    route.route_id,
                ),
            )
            if len(ranked) > 1:
                first_key = (
                    abs(ranked[0].src.start - line_hint[0]),
                    ranked[0].src.end,
                )
                second_key = (
                    abs(ranked[1].src.start - line_hint[0]),
                    ranked[1].src.end,
                )
                if first_key == second_key:
                    return None, (
                        "ambiguous_line_hint_candidates:"
                        + ",".join(route.route_id for route in ranked[:5])
                    )
            return ranked[0], ""

    if not stub_tokens:
        if len(scoped) == 1:
            return scoped[0], ""
        return None, (
            "insufficient_stub_evidence_multiple_candidates:"
            + ",".join(route.route_id for route in scoped[:5])
        )

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
        return None, "no_token_overlap"

    scored.sort(
        key=lambda item: (
            item[0],
            -item[1].src.start,
            item[1].route_id,
        ),
        reverse=True,
    )
    best_score = scored[0][0]
    top = [item for item in scored if abs(item[0] - best_score) < 1e-9]
    if len(top) > 1:
        return None, (
            "ambiguous_token_overlap_candidates:" + ",".join(route.route_id for _, route in top[:5])
        )

    score, route = scored[0]
    if score < min_score:
        return None, f"score_below_threshold:{score:.3f}<{min_score:.3f}"
    return route, ""


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
        route.unresolved_refs = []
        if not route.ref_stubs:
            continue

        unresolved_stubs: list[str] = []
        unresolved_refs: list[UnresolvedReference] = []
        for stub in route.ref_stubs:
            stub_text = str(stub).strip()
            if not stub_text:
                continue

            resolved_route: RouteEntry | None = None
            unresolved_reason = ""
            route_id_match = _ROUTE_ID_PATTERN.search(stub_text)
            if route_id_match:
                resolved_route = routes_by_route_id.get(route_id_match.group(0).upper())
                if resolved_route is None:
                    unresolved_reason = f"unknown_route_id:{route_id_match.group(0).upper()}"
            if resolved_route is None:
                element_match = _ELEMENT_ID_PATTERN.search(stub_text)
                if element_match:
                    resolved_route = routes_by_element_id.get(element_match.group(0).upper())
                    if resolved_route is None:
                        unresolved_reason = f"unknown_element_id:{element_match.group(0).upper()}"

            line_hint = _extract_line_hint(stub_text)
            if resolved_route is None:
                target_file, file_reason = _resolve_stub_file(stub_text, alias_to_files)
                if file_reason and not unresolved_reason:
                    unresolved_reason = file_reason
                if target_file:
                    candidates = [
                        candidate
                        for candidate in routes_by_file.get(target_file, [])
                        if candidate.route_id != route.route_id
                    ]
                    resolved_route, candidate_reason = _pick_best_route_candidate(
                        candidates=candidates,
                        stub_tokens=_tokenize(stub_text),
                        token_cache=token_cache,
                        line_hint=line_hint,
                        min_score=0.0,
                    )
                    if candidate_reason:
                        unresolved_reason = candidate_reason

            if resolved_route is None:
                candidates = [
                    candidate
                    for candidate in routes
                    if candidate.route_id != route.route_id and candidate.src.file != route.src.file
                ]
                resolved_route, fallback_reason = _pick_best_route_candidate(
                    candidates=candidates,
                    stub_tokens=_tokenize(stub_text),
                    token_cache=token_cache,
                    line_hint=line_hint,
                    min_score=0.35,
                )
                if fallback_reason:
                    unresolved_reason = fallback_reason

            if resolved_route is None:
                unresolved_stubs.append(stub_text)
                unresolved_refs.append(
                    UnresolvedReference(
                        stub=stub_text,
                        reason=unresolved_reason or "unresolved_reference",
                    )
                )
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
        route.unresolved_refs = unresolved_refs

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
    destination_context: str,
    output_dir: Path,
    *,
    intake_mode: IntakeMode,
) -> list[RouteEntry]:
    """Route a single source file. Returns RouteEntry list."""
    numbered_content, total_lines = _build_numbered_content(source_file)

    if total_lines == 0:
        logger.warning("Skipping empty file: %s", source_file.name)
        return []

    destination_field = "destination" if intake_mode == INTAKE_MODE_INTENT else "library"
    destination_hint = (
        "Set `destination` to one of: system/workflows, system/entities, system/interfaces."
        if intake_mode == INTAKE_MODE_INTENT
        else "Set `library` to one of the available library IDs."
    )
    prompt = (
        f"{_CLASSIFICATION_GUIDANCE}\n\n"
        f"{destination_context}\n\n"
        "## Output Requirements\n\n"
        "Return JSON with a top-level `routes` array.\n"
        f"Each route MUST include: `start`, `end`, `{destination_field}`, `bucket`, "
        "`element_id`, `notes`, `ref_stubs`.\n"
        f"{destination_hint}\n"
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
    entries = _parse_route_entries(
        data,
        rel_path,
        intake_mode=intake_mode,
        total_lines=total_lines,
    )
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
    *,
    intake_mode: IntakeMode | str = INTAKE_MODE_PROSE,
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

    normalized_mode = normalize_intake_mode(str(intake_mode))
    rediscovery_enabled = normalized_mode == INTAKE_MODE_PROSE

    source_files = sorted(source_dir.glob("**/*.md"))
    if not source_files:
        logger.warning("No .md files found in %s", source_dir)
        return [], libraries

    current_libraries = list(libraries)
    all_routes: list[RouteEntry] = []
    pending_files = list(source_files)

    max_rounds = _MAX_REDISCOVERY_ROUNDS if rediscovery_enabled else 0
    for rediscovery_round in range(max_rounds + 1):
        destination_context = _build_destination_context(
            current_libraries,
            intake_mode=normalized_mode,
        )
        failed_files: list[Path] = []
        failed_errors: list[str] = []

        for source_file in pending_files:
            logger.info("Routing %s", source_file.name)
            try:
                entries = _route_file(
                    source_file,
                    source_dir,
                    destination_context,
                    output_dir,
                    intake_mode=normalized_mode,
                )
                all_routes.extend(entries)
            except RouteParseError as e:
                error_msg = str(e)
                if rediscovery_enabled and e.code == "missing_destination":
                    failed_files.append(source_file)
                    failed_errors.append(f"{e.code}: {error_msg}")
                    logger.warning(
                        "Routing %s failed (%s): %s",
                        source_file.name,
                        e.code,
                        error_msg,
                    )
                else:
                    raise

        if not failed_files:
            break

        if not rediscovery_enabled:
            raise ValueError(
                f"Routing failed for {len(failed_files)} files in intent mode. "
                f"Files: {[f.name for f in failed_files]}. Errors: {failed_errors}"
            )

        if rediscovery_round >= max_rounds:
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
            intake_mode=normalized_mode,
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
                    "destination": entry.library,
                    **({"library": entry.library} if normalized_mode == INTAKE_MODE_PROSE else {}),
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
                "unresolved_refs": [
                    {
                        "stub": ref.stub,
                        "reason": ref.reason,
                    }
                    for ref in entry.unresolved_refs
                ],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info("Total routes: %d across %d files", len(all_routes), len(source_files))
    return all_routes, current_libraries
