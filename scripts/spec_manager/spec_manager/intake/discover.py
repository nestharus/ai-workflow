"""Step 2: Library discovery from summaries."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from spec_manager.core.agent_utils import run_agent
from spec_manager.intake.types import LibraryDef
from spec_manager.refinement.formats import _strip_code_fences

logger = logging.getLogger(__name__)


def discover_libraries(
    summaries: list[dict],
    output_dir: Path,
    *,
    existing_libraries: list[LibraryDef] | None = None,
    unroutable_files: list[str] | None = None,
) -> list[LibraryDef]:
    """Discover libraries from file summaries.

    Args:
        summaries: List of file summary dicts from Step 1.
        output_dir: Directory for writing output artifacts.
        existing_libraries: If provided, libraries already discovered.
            The agent must keep all of these and discover additional ones.
        unroutable_files: File IDs that could not be routed to any
            existing library. Signals that new libraries are needed.

    Returns:
        List of discovered LibraryDef objects.
    """
    if not summaries:
        logger.warning("No summaries provided for library discovery")
        return []

    prompt_parts = ["## INPUT DATA\n\n"]

    if existing_libraries and unroutable_files:
        prompt_parts.append("### Existing Libraries (KEEP ALL)\n\n")
        for lib in existing_libraries:
            prompt_parts.append(
                f"- **{lib.lib_id}**: {lib.name} — {lib.description}\n"
            )
        prompt_parts.append(
            f"\n### Unroutable Files\n\n"
            f"The following files contain non-constraint content that could "
            f"not be routed to any existing library. Additional libraries "
            f"are needed based on cohesion/coupling analysis:\n\n"
        )
        for file_id in unroutable_files:
            prompt_parts.append(f"- {file_id}\n")
        prompt_parts.append("\n")

    prompt_parts.append(
        "File summaries:\n\n"
        f"{json.dumps(summaries, indent=2, ensure_ascii=False)}"
    )
    prompt = "".join(prompt_parts)

    last_json_error: json.JSONDecodeError | None = None
    for attempt in range(3):
        raw_output = run_agent(
            agent_name="spec-intake-discover-libraries",
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
                "JSON parse attempt %d/3 failed for library discovery: %s",
                attempt + 1,
                cleaned[:200],
            )
    else:
        raise ValueError(
            f"Failed to parse library discovery JSON after 3 attempts: {last_json_error}"
        )

    # Write full discovery output
    libraries_file = output_dir / "libraries.json"
    libraries_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if "libraries" not in data:
        raise ValueError(
            f"Library discovery JSON missing 'libraries' key. Got keys: {sorted(data.keys())}"
        )

    libraries: list[LibraryDef] = []
    for lib_data in data["libraries"]:
        libraries.append(
            LibraryDef(
                lib_id=lib_data["lib_id"],
                name=lib_data["name"],
                description=lib_data["description"],
            )
        )

    logger.info(
        "Discovered %d libraries: %s",
        len(libraries),
        ", ".join(lib.lib_id for lib in libraries),
    )
    return libraries
