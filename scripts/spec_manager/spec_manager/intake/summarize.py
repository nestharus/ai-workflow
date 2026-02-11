"""Step 1: LLM summarization per source file for routing decisions."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.formats import _strip_code_fences

logger = logging.getLogger(__name__)


def summarize_sources(source_dir: Path, output_dir: Path) -> list[dict]:
    """Summarize all markdown source files for routing decisions.

    Args:
        source_dir: Directory containing source .md files.
        output_dir: Directory for writing summary outputs.

    Returns:
        List of parsed summary dicts, one per source file.
    """
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

        prompt = f"## INPUT DATA\n\nFile: {source_file.relative_to(source_dir)}\n\n{content}"

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
        summary["file_id"] = source_file.stem

        # Write individual summary
        summary_file = summaries_dir / f"{source_file.stem}.json"
        summary_file.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        summaries.append(summary)

    logger.info("Summarized %d files", len(summaries))
    return summaries
