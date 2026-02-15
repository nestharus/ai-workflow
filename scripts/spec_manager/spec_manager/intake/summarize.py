"""Step 1: LLM summarization per source file for routing decisions."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from spec_manager.core.agent_utils import run_agent
from spec_manager.intake.types import INTAKE_MODE_PROSE, IntakeMode, normalize_intake_mode
from spec_manager.refinement.formats import _strip_code_fences

logger = logging.getLogger(__name__)


def _pick_first_text(summary: dict, keys: tuple[str, ...]) -> str:
    """Pick the first non-empty string value from candidate keys."""
    for key in keys:
        value = summary.get(key, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _as_text_list(value: object) -> list[str]:
    """Normalize an arbitrary value into a compact list of strings."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _render_summary_markdown(
    source_rel_path: str,
    summary: dict,
    *,
    include_decomposition_hints: bool,
) -> str:
    """Render a high-level routing summary artifact as markdown."""
    overview = _pick_first_text(
        summary,
        ("summary", "high_level_summary", "overview", "file_summary"),
    )
    concerns = _as_text_list(
        summary.get("core_concerns")
        or summary.get("candidate_responsibilities")
        or summary.get("responsibilities")
        or summary.get("topics")
    )
    library_hints = (
        _as_text_list(
            summary.get("library_hints")
            or summary.get("candidate_libraries")
            or summary.get("libraries")
        )
        if include_decomposition_hints
        else []
    )

    lines = [
        "# Routing Summary",
        "",
        f"- Source: `{source_rel_path}`",
        f"- File ID: `{summary.get('file_id', '')}`",
        "",
    ]
    if overview:
        lines.extend(["## Overview", overview, ""])
    if concerns:
        lines.append("## Core Concerns")
        lines.extend(f"- {item}" for item in concerns[:12])
        lines.append("")
    if library_hints:
        lines.append("## Library Hints")
        lines.extend(f"- {item}" for item in library_hints[:12])
        lines.append("")
    if not overview and not concerns and not library_hints:
        lines.extend(
            [
                "## Overview",
                "High-level routing hints were unavailable in structured fields.",
                "",
            ]
        )
    return "\n".join(lines)


def summarize_sources(
    source_dir: Path,
    output_dir: Path,
    *,
    intake_mode: IntakeMode | str = INTAKE_MODE_PROSE,
) -> list[dict]:
    """Summarize all markdown source files for routing decisions.

    Args:
        source_dir: Directory containing source .md files.
        output_dir: Directory for writing summary outputs.

    Returns:
        List of parsed summary dicts, one per source file.
    """
    normalized_mode = normalize_intake_mode(str(intake_mode))
    include_decomposition_hints = normalized_mode == INTAKE_MODE_PROSE

    summaries_dir = output_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    source_files = sorted(source_dir.glob("**/*.md"))
    if not source_files:
        logger.warning("No .md files found in %s", source_dir)
        return []

    summaries: list[dict] = []
    for source_file in source_files:
        logger.info("Summarizing %s", source_file.name)
        content = source_file.read_text(encoding="utf-8")
        if not content.strip():
            logger.warning("Skipping empty file: %s", source_file.name)
            continue

        mode_guidance = ""
        if not include_decomposition_hints:
            mode_guidance = (
                "## MODE\n"
                "Input is intent-level. Summarize domain concerns and behavioral intent only.\n"
                "Do NOT suggest library/module decomposition.\n\n"
            )

        prompt = (
            f"{mode_guidance}"
            f"## INPUT DATA\n\n"
            f"File: {source_file.relative_to(source_dir)}\n\n{content}"
        )

        last_json_error: json.JSONDecodeError | None = None
        for attempt in range(3):
            raw_output = run_agent(
                agent_name="spec-intake-summarize",
                prompt=prompt,
                workspace=output_dir,
            )

            cleaned = _strip_code_fences(raw_output)
            try:
                summary = json.loads(cleaned)
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
                f"Failed to parse summary JSON for {source_file.name} "
                f"after 3 attempts: {last_json_error}"
            )

        # Override file_id — LLM may mangle it (e.g. $ instead of _).
        llm_file_id = summary.get("file_id", "")
        canonical_id = source_file.stem
        if llm_file_id and llm_file_id != canonical_id:
            # C00: Surface ambiguity — record the override
            logger.info(
                "Overriding LLM file_id %r with canonical %r for %s",
                llm_file_id,
                canonical_id,
                source_file.name,
            )
        summary["file_id"] = canonical_id

        if not include_decomposition_hints:
            for key in ("library_hints", "candidate_libraries", "libraries"):
                summary.pop(key, None)

        # Write high-level routing summary artifact.
        source_rel_path = str(source_file.relative_to(source_dir))
        summary_file = summaries_dir / f"{source_file.stem}.md"
        summary_file.write_text(
            _render_summary_markdown(
                source_rel_path,
                summary,
                include_decomposition_hints=include_decomposition_hints,
            ),
            encoding="utf-8",
        )

        summaries.append(summary)

    logger.info("Summarized %d files", len(summaries))
    return summaries
