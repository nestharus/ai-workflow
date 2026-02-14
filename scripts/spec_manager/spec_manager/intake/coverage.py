"""Step 4: Coverage closure for routing-table completeness."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from spec_manager.intake.types import CoverageException, CoverageLedgerEntry, RouteEntry

logger = logging.getLogger(__name__)

_MAX_FILTER_ITERATIONS = 3


def _collect_explicit_ignored_ranges(
    ignored_marks: list[bool],
    ignored_route_ids: dict[int, list[str]],
) -> list[CoverageException]:
    """Convert per-line IGNORED route marks into contiguous ranges."""
    exceptions: list[CoverageException] = []
    line_count = len(ignored_marks) - 1
    line_num = 1
    while line_num <= line_count:
        if not ignored_marks[line_num]:
            line_num += 1
            continue

        start = line_num
        route_ids: set[str] = set()
        while line_num <= line_count and ignored_marks[line_num]:
            route_ids.update(ignored_route_ids.get(line_num, []))
            line_num += 1

        exceptions.append(
            CoverageException(
                start=start,
                end=line_num - 1,
                status="ignored",
                route_ids=sorted(route_ids),
                reason="explicitly ignored during routing",
            )
        )

    return exceptions


def check_coverage(
    source_dir: Path,
    routes: list[RouteEntry],
    output_dir: Path,
) -> list[CoverageLedgerEntry]:
    """Check per-file routing completeness for all source files.

    Each source file receives one ledger record:
    - ``fully_routed``: all lines are routed or explicitly ignored.
    - ``incomplete``: at least one line remains uncovered.
    """
    routed_routes: dict[str, list[RouteEntry]] = defaultdict(list)
    ignored_routes: dict[str, list[RouteEntry]] = defaultdict(list)
    for route in routes:
        if route.bucket == "IGNORED":
            ignored_routes[route.src.file].append(route)
        else:
            routed_routes[route.src.file].append(route)

    source_files = sorted(source_dir.glob("**/*.md"))
    if not source_files:
        logger.warning("No .md files found in %s", source_dir)
        return []

    file_lines: dict[str, list[str]] = {}
    uncovered_ranges: list[tuple[str, int, int]] = []
    explicit_ignored: dict[str, list[CoverageException]] = defaultdict(list)
    total_lines = 0

    for source_file in source_files:
        rel_path = str(source_file.relative_to(source_dir))
        lines = source_file.read_text(encoding="utf-8").splitlines()
        file_lines[rel_path] = lines
        line_count = len(lines)
        total_lines += line_count

        if line_count == 0:
            continue

        covered = [False] * (line_count + 1)
        ignored_marks = [False] * (line_count + 1)
        ignored_route_ids: dict[int, list[str]] = defaultdict(list)

        for route in routed_routes.get(rel_path, []):
            start = max(1, route.src.start)
            end = min(line_count, route.src.end)
            if start > end:
                continue
            for line_num in range(start, end + 1):
                covered[line_num] = True

        for route in ignored_routes.get(rel_path, []):
            start = max(1, route.src.start)
            end = min(line_count, route.src.end)
            if start > end:
                continue
            for line_num in range(start, end + 1):
                covered[line_num] = True
                ignored_marks[line_num] = True
                ignored_route_ids[line_num].append(route.route_id)

        if any(ignored_marks):
            explicit_ignored[rel_path].extend(
                _collect_explicit_ignored_ranges(ignored_marks, ignored_route_ids)
            )

        line_num = 1
        while line_num <= line_count:
            if covered[line_num]:
                line_num += 1
                continue
            start = line_num
            while line_num <= line_count and not covered[line_num]:
                line_num += 1
            uncovered_ranges.append((rel_path, start, line_num - 1))

    llm_classified = (
        _classify_uncovered(uncovered_ranges, file_lines, output_dir) if uncovered_ranges else {}
    )

    all_exceptions: dict[str, list[CoverageException]] = {
        file_path: list(exceptions) for file_path, exceptions in explicit_ignored.items()
    }
    for file_path, exceptions in llm_classified.items():
        all_exceptions.setdefault(file_path, []).extend(exceptions)

    ledger: list[CoverageLedgerEntry] = []
    unresolved_lines = 0
    ignored_lines = 0

    for source_file in source_files:
        rel_path = str(source_file.relative_to(source_dir))
        line_count = len(file_lines[rel_path])
        exceptions = all_exceptions.get(rel_path, [])
        exceptions.sort(key=lambda exc: exc.start)

        unresolved = [exc for exc in exceptions if exc.status == "uncovered"]
        ignored = [exc for exc in exceptions if exc.status == "ignored"]
        unresolved_lines += sum(exc.end - exc.start + 1 for exc in unresolved)
        ignored_lines += sum(exc.end - exc.start + 1 for exc in ignored)

        ledger.append(
            CoverageLedgerEntry(
                file=rel_path,
                start=1 if line_count > 0 else 0,
                end=line_count,
                status="fully_routed" if not unresolved else "incomplete",
                exceptions=exceptions,
            )
        )

    ledger_path = output_dir / "coverage_ledger.jsonl"
    with ledger_path.open("w", encoding="utf-8") as handle:
        for entry in ledger:
            record: dict[str, Any] = {
                "file": entry.file,
                "start": entry.start,
                "end": entry.end,
                "status": entry.status,
                "exceptions": [
                    {
                        "start": exc.start,
                        "end": exc.end,
                        "status": exc.status,
                        **({"route_ids": exc.route_ids} if exc.route_ids else {}),
                        **({"reason": exc.reason} if exc.reason else {}),
                    }
                    for exc in entry.exceptions
                ],
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    incomplete_files = [entry for entry in ledger if entry.status == "incomplete"]
    accounted_lines = total_lines - unresolved_lines
    coverage_pct = (accounted_lines / total_lines * 100.0) if total_lines > 0 else 100.0
    logger.info(
        "Coverage: %d/%d lines accounted for (%.1f%%), %d lines ignored",
        accounted_lines,
        total_lines,
        coverage_pct,
        ignored_lines,
    )
    if incomplete_files:
        logger.warning(
            "Coverage incomplete for %d files with %d unresolved lines",
            len(incomplete_files),
            unresolved_lines,
        )

    return ledger


def _classify_uncovered(
    ranges: list[tuple[str, int, int]],
    file_lines: dict[str, list[str]],
    output_dir: Path,
) -> dict[str, list[CoverageException]]:
    """Classify uncovered ranges as ignored noise or unresolved content gaps."""
    from spec_manager.core.agent_utils import run_agent
    from spec_manager.refinement.formats import _strip_code_fences

    payload: list[dict[str, Any]] = []
    for file_path, start, end in ranges:
        lines = file_lines.get(file_path, [])
        content: list[str] = []
        for line_num in range(start, end + 1):
            if 1 <= line_num <= len(lines):
                content.append(f"{line_num}: {lines[line_num - 1]}")
        payload.append(
            {
                "id": f"{file_path}:{start}-{end}",
                "file": file_path,
                "start": start,
                "end": end,
                "content": content,
            }
        )

    current_payload = payload
    filter_script: str | None = None
    classifications: dict[str, str] = {}
    reasons: dict[str, str] = {}

    for iteration in range(1, _MAX_FILTER_ITERATIONS + 1):
        prompt_parts = [
            "## INPUT DATA\n",
            f"Iteration {iteration} of {_MAX_FILTER_ITERATIONS}.\n",
            f"Uncovered line ranges ({len(current_payload)} ranges):\n\n",
            json.dumps(current_payload, indent=2, ensure_ascii=False),
        ]
        if filter_script:
            prompt_parts.append(
                f"\n\n## Previous filter script\n\n```python\n{filter_script}\n```\n"
                "\nReview the previous results. Adjust the script if it filters "
                "too much (removes real spec content) or too little (keeps noise)."
            )

        last_json_error: json.JSONDecodeError | None = None
        for attempt in range(3):
            raw = run_agent(
                agent_name="spec-intake-coverage-filter",
                prompt="\n".join(prompt_parts),
                workspace=output_dir,
            )
            cleaned = _strip_code_fences(raw)
            try:
                result = json.loads(cleaned)
                break
            except json.JSONDecodeError as error:
                last_json_error = error
                logger.warning(
                    "JSON parse attempt %d/3 failed for coverage filter (iter %d): %s",
                    attempt + 1,
                    iteration,
                    cleaned[:200],
                )
        else:
            raise ValueError(
                f"Failed to parse coverage filter JSON (iter {iteration}) "
                f"after 3 attempts: {last_json_error}"
            )

        if "classifications" not in result:
            raise ValueError(
                f"Coverage filter JSON (iter {iteration}) missing 'classifications' key. "
                f"Got keys: {sorted(result.keys())}"
            )

        for item in result["classifications"]:
            item_id = item.get("id")
            if item_id is None:
                raise ValueError(f"Classification item missing 'id': {item}")
            verdict = item.get("verdict")
            if verdict not in ("noise", "content"):
                raise ValueError(
                    f"Invalid verdict {verdict!r} for {item_id}. Must be 'noise' or 'content'."
                )
            classifications[item_id] = verdict
            reasons[item_id] = item.get("reason", "")

        filter_script = result.get("filter_script", "")
        if result.get("stable", False):
            logger.info("Coverage filter stabilized at iteration %d", iteration)
            break

        current_payload = [
            item
            for item in current_payload
            if classifications.get(item["id"], "content") == "content"
        ]
        if not current_payload:
            break

    classified: dict[str, list[CoverageException]] = defaultdict(list)
    for file_path, start, end in ranges:
        item_id = f"{file_path}:{start}-{end}"
        verdict = classifications.get(item_id, "content")
        if verdict == "noise":
            classified[file_path].append(
                CoverageException(
                    start=start,
                    end=end,
                    status="ignored",
                    reason=reasons.get(item_id, "formatting"),
                )
            )
        else:
            classified[file_path].append(
                CoverageException(
                    start=start,
                    end=end,
                    status="uncovered",
                    reason=reasons.get(item_id, "requires routing decision"),
                )
            )

    return dict(classified)
