"""Step 4: Coverage check with LLM-assisted noise classification.

After the deterministic routing scan, uncovered lines are passed to an LLM
which generates a filtering script to separate format noise from real content
gaps.  The LLM iterates the script until the filtered result is stable —
keeping all genuine content, ignoring all noise.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from spec_manager.intake.types import CoverageLedgerEntry, RouteEntry

logger = logging.getLogger(__name__)

_MAX_FILTER_ITERATIONS = 3


def check_coverage(
    source_dir: Path,
    routes: list[RouteEntry],
    output_dir: Path,
) -> list[CoverageLedgerEntry]:
    """Check that every source line is covered by at least one route.

    Two passes:
      1. Deterministic — mark lines routed or uncovered based on route spans.
      2. LLM — classify uncovered lines as noise (ignored) or real gaps.

    Args:
        source_dir: Directory containing source .md files.
        routes: List of routing entries from Step 3.
        output_dir: Directory for writing the coverage ledger.

    Returns:
        List of CoverageLedgerEntry objects.
    """
    # --- Pass 1: deterministic scan ---
    file_routes: dict[str, list[RouteEntry]] = defaultdict(list)
    for route in routes:
        file_routes[route.src.file].append(route)

    source_files = sorted(source_dir.glob("**/*.md"))
    ledger: list[CoverageLedgerEntry] = []
    total_lines = 0
    covered_lines = 0

    # Per-file line content needed for LLM pass
    file_lines: dict[str, list[str]] = {}
    uncovered_entries: list[CoverageLedgerEntry] = []

    for source_file in source_files:
        rel_path = str(source_file.relative_to(source_dir))
        lines = source_file.read_text(encoding="utf-8").splitlines()
        file_lines[rel_path] = lines
        line_count = len(lines)
        total_lines += line_count

        if line_count == 0:
            continue

        covered = [False] * (line_count + 1)
        line_route_ids: dict[int, list[str]] = defaultdict(list)

        for route in file_routes.get(rel_path, []):
            for line_num in range(route.src.start, route.src.end + 1):
                if 1 <= line_num <= line_count:
                    covered[line_num] = True
                    line_route_ids[line_num].append(route.route_id)

        i = 1
        while i <= line_count:
            if covered[i]:
                start = i
                route_ids: set[str] = set()
                while i <= line_count and covered[i]:
                    route_ids.update(line_route_ids[i])
                    i += 1
                end = i - 1
                covered_lines += end - start + 1
                ledger.append(
                    CoverageLedgerEntry(
                        file=rel_path, start=start, end=end,
                        status="routed", route_ids=sorted(route_ids),
                    )
                )
            else:
                start = i
                while i <= line_count and not covered[i]:
                    i += 1
                end = i - 1
                entry = CoverageLedgerEntry(
                    file=rel_path, start=start, end=end, status="uncovered",
                )
                uncovered_entries.append(entry)

    # --- Pass 2: LLM classification of uncovered lines ---
    if uncovered_entries:
        classified = _classify_uncovered(uncovered_entries, file_lines, output_dir)
        for entry in classified:
            if entry.status == "ignored":
                covered_lines += entry.end - entry.start + 1
        ledger.extend(classified)
    else:
        covered_lines = total_lines

    # Sort ledger by file then start line
    ledger.sort(key=lambda e: (e.file, e.start))

    # --- Write ledger ---
    ledger_path = output_dir / "coverage_ledger.jsonl"
    with ledger_path.open("w", encoding="utf-8") as f:
        for entry in ledger:
            record: dict[str, Any] = {
                "file": entry.file,
                "start": entry.start,
                "end": entry.end,
                "status": entry.status,
            }
            if entry.route_ids:
                record["route_ids"] = entry.route_ids
            if entry.ignore_reason:
                record["ignore_reason"] = entry.ignore_reason
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    uncovered_count = sum(1 for e in ledger if e.status == "uncovered")
    coverage_pct = (covered_lines / total_lines * 100) if total_lines > 0 else 100.0
    logger.info("Coverage: %d/%d lines (%.1f%%)", covered_lines, total_lines, coverage_pct)
    if uncovered_count:
        logger.warning("Uncovered content ranges: %d", uncovered_count)

    return ledger


def _classify_uncovered(
    entries: list[CoverageLedgerEntry],
    file_lines: dict[str, list[str]],
    output_dir: Path,
) -> list[CoverageLedgerEntry]:
    """Use GLM to classify uncovered lines as noise or real content gaps.

    The LLM generates a filter script, applies it, reviews the result, and
    iterates until satisfied.  Returns updated entries with status set to
    either ``"ignored"`` (with reason) or ``"uncovered"``.
    """
    from spec_manager.core.agent_utils import run_agent
    from spec_manager.refinement.formats import _strip_code_fences

    # Build the uncovered-lines payload for the LLM
    uncovered_payload: list[dict[str, Any]] = []
    for entry in entries:
        lines = file_lines.get(entry.file, [])
        content_lines = []
        for line_num in range(entry.start, entry.end + 1):
            if 1 <= line_num <= len(lines):
                content_lines.append(f"{line_num}: {lines[line_num - 1]}")
        uncovered_payload.append({
            "id": f"{entry.file}:{entry.start}-{entry.end}",
            "file": entry.file,
            "start": entry.start,
            "end": entry.end,
            "content": content_lines,
        })

    # Iteration loop: generate filter, review, refine
    current_payload = uncovered_payload
    filter_script: str | None = None
    classifications: dict[str, str] = {}  # id -> "noise"|"content"
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
        for json_attempt in range(3):
            raw = run_agent(
                agent_name="spec-intake-coverage-filter",
                prompt="\n".join(prompt_parts),
                workspace=output_dir,
            )

            cleaned = _strip_code_fences(raw)
            try:
                result = json.loads(cleaned)
                break
            except json.JSONDecodeError as e:
                last_json_error = e
                logger.warning(
                    "JSON parse attempt %d/3 failed for coverage filter (iter %d): %s",
                    json_attempt + 1,
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

        # Accumulate classifications across iterations
        for item in result["classifications"]:
            item_id = item.get("id")
            if item_id is None:
                raise ValueError(f"Classification item missing 'id': {item}")
            verdict = item.get("verdict")
            if verdict not in ("noise", "content"):
                raise ValueError(
                    f"Invalid verdict {verdict!r} for {item_id}. "
                    f"Must be 'noise' or 'content'."
                )
            classifications[item_id] = verdict
            reasons[item_id] = item.get("reason", "")

        filter_script = result.get("filter_script", "")

        # Check if the LLM is satisfied
        if result.get("stable", False):
            logger.info("Coverage filter stabilized at iteration %d", iteration)
            break

        # Build next iteration payload with only items marked "content"
        current_payload = [
            p for p in current_payload
            if classifications.get(p["id"], "content") == "content"
        ]
        if not current_payload:
            break

    # Build final classified entries
    classified: list[CoverageLedgerEntry] = []
    for entry in entries:
        entry_id = f"{entry.file}:{entry.start}-{entry.end}"
        verdict = classifications.get(entry_id, "content")
        if verdict == "noise":
            classified.append(CoverageLedgerEntry(
                file=entry.file, start=entry.start, end=entry.end,
                status="ignored", ignore_reason=reasons.get(entry_id, "formatting"),
            ))
        else:
            classified.append(CoverageLedgerEntry(
                file=entry.file, start=entry.start, end=entry.end,
                status="uncovered",
            ))

    return classified
