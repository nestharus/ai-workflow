"""Step 2: Library discovery from summaries."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from spec_manager.core.agent_utils import run_agent
from spec_manager.intake.types import (
    INTAKE_MODE_INTENT,
    INTAKE_MODE_PROSE,
    IntakeMode,
    LibraryDef,
    normalize_intake_mode,
)
from spec_manager.refinement.formats import _strip_code_fences

logger = logging.getLogger(__name__)


def _parse_library_defs(payload: object, *, context: str) -> list[LibraryDef]:
    """Parse a library payload into validated ``LibraryDef`` objects."""
    if not isinstance(payload, list):
        raise TypeError(
            f"{context} expected 'libraries' to be a list. Got: {type(payload).__name__}"
        )

    libraries: list[LibraryDef] = []
    seen_ids: set[str] = set()
    for idx, lib_data in enumerate(payload, start=1):
        if not isinstance(lib_data, dict):
            raise TypeError(f"{context} library #{idx} is not an object: {lib_data!r}")

        lib_id = str(lib_data.get("lib_id", "")).strip()
        name = str(lib_data.get("name", "")).strip()
        description = str(lib_data.get("description", "")).strip()
        if not lib_id or not name or not description:
            raise ValueError(
                f"{context} library #{idx} missing required fields: "
                f"lib_id={lib_id!r}, name={name!r}, description={description!r}"
            )
        if lib_id in seen_ids:
            raise ValueError(f"{context} includes duplicate library id: {lib_id}")
        seen_ids.add(lib_id)
        libraries.append(
            LibraryDef(
                lib_id=lib_id,
                name=name,
                description=description,
            )
        )
    return libraries


def _merge_library_sets(
    discovered: list[LibraryDef],
    *,
    existing_libraries: list[LibraryDef] | None,
) -> list[LibraryDef]:
    """Merge discovered libraries additively, preserving all existing libraries."""
    if not existing_libraries:
        return discovered

    merged = list(existing_libraries)
    existing_by_id = {lib.lib_id: lib for lib in existing_libraries}
    for discovered_lib in discovered:
        existing = existing_by_id.get(discovered_lib.lib_id)
        if existing is not None:
            if (
                existing.name != discovered_lib.name
                or existing.description != discovered_lib.description
            ):
                logger.warning(
                    "Ignoring conflicting rediscovery for existing library %s: "
                    "existing=(%r, %r) discovered=(%r, %r)",
                    existing.lib_id,
                    existing.name,
                    existing.description,
                    discovered_lib.name,
                    discovered_lib.description,
                )
            continue
        merged.append(discovered_lib)
        existing_by_id[discovered_lib.lib_id] = discovered_lib
    return merged


def discover_libraries(
    summaries: list[dict],
    output_dir: Path,
    *,
    intake_mode: IntakeMode | str = INTAKE_MODE_PROSE,
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
    normalized_mode = normalize_intake_mode(str(intake_mode))
    if normalized_mode == INTAKE_MODE_INTENT:
        logger.info("Skipping library discovery for intent-level intake mode")
        return list(existing_libraries or [])

    if not summaries:
        logger.warning("No summaries provided for library discovery")
        return []

    prompt_parts = ["## INPUT DATA\n\n"]

    if existing_libraries and unroutable_files:
        prompt_parts.append("### Existing Libraries (KEEP ALL)\n\n")
        for lib in existing_libraries:
            prompt_parts.append(f"- **{lib.lib_id}**: {lib.name} — {lib.description}\n")
        prompt_parts.append(
            "\n### Unroutable Files\n\n"
            "The following files contain non-constraint content that could "
            "not be routed to any existing library. Additional libraries "
            "are needed based on cohesion/coupling analysis:\n\n"
        )
        for file_id in unroutable_files:
            prompt_parts.append(f"- {file_id}\n")
        prompt_parts.append("\n")

    prompt_parts.append(f"File summaries:\n\n{json.dumps(summaries, indent=2, ensure_ascii=False)}")
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

    if "libraries" not in data:
        raise ValueError(
            f"Library discovery JSON missing 'libraries' key. Got keys: {sorted(data.keys())}"
        )

    discovered_libraries = _parse_library_defs(
        data["libraries"],
        context="Library discovery",
    )
    libraries = _merge_library_sets(
        discovered_libraries,
        existing_libraries=existing_libraries,
    )

    libraries_file = output_dir / "libraries.yaml"
    libraries_file.write_text(
        yaml.safe_dump(
            {
                "libraries": [
                    {
                        "lib_id": lib.lib_id,
                        "name": lib.name,
                        "description": lib.description,
                    }
                    for lib in libraries
                ]
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    logger.info(
        "Discovered %d libraries: %s",
        len(libraries),
        ", ".join(lib.lib_id for lib in libraries),
    )
    return libraries
