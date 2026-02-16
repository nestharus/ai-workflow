"""Post-completion hooks for hollowing out specs."""

from __future__ import annotations

import json
import logging

from spec_manager.core.evidence_index import EvidenceIndex
from spec_manager.refinement.hollowed_spec.extractor import hollow_out_spec
from spec_manager.refinement.workspace import WorkspaceManager

logger = logging.getLogger(__name__)


def on_spec_completed(
    lib_id: str,
    manager: WorkspaceManager,
) -> None:
    """Hook called when a library spec reaches completion.

    Hollows out the spec and updates the evidence index.

    Args:
        lib_id: Library ID whose spec was completed
        manager: Workspace manager
    """
    # Find the spec.md file for this library
    lib_dir = manager.structure.libraries_dir / lib_id
    spec_path = lib_dir / "spec.md"

    if not spec_path.exists():
        logger.warning("No spec.md found for %s at %s", lib_id, spec_path)
        return

    spec_content = spec_path.read_text(encoding="utf-8")
    if not spec_content.strip():
        logger.warning("Empty spec.md for %s", lib_id)
        return

    # Hollow out the spec
    hollowed = hollow_out_spec(lib_id, spec_content)

    # Check if we need to re-hollow (spec_hash comparison)
    evidence_store_dir = manager.structure.workspace_dir / "evidence_store" / lib_id
    hollowed_path = evidence_store_dir / "hollowed_spec.json"

    if hollowed_path.exists():
        try:
            existing_data = json.loads(hollowed_path.read_text(encoding="utf-8"))
            existing_hash = existing_data.get("spec_hash", "")
            if existing_hash == hollowed.spec_hash:
                logger.info(
                    "Spec for %s unchanged (hash=%s), skipping re-hollow",
                    lib_id,
                    existing_hash[:8],
                )
                return
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "Failed reading existing hollowed spec at %s; re-hollowing",
                hollowed_path,
                exc_info=True,
            )

    # Write hollowed spec
    evidence_store_dir.mkdir(parents=True, exist_ok=True)
    hollowed_path.write_text(
        json.dumps(hollowed.model_dump(), indent=2),
        encoding="utf-8",
    )
    logger.info(
        "Hollowed spec for %s: %d sections, %d paragraphs",
        lib_id,
        len(hollowed.sections),
        len(hollowed.paragraphs),
    )

    # Update the evidence index
    index_path = manager.structure.workspace_dir / "indexes" / "evidence_store_index.json"
    if index_path.exists():
        try:
            index = EvidenceIndex.load(index_path)
        except Exception:
            logger.warning(
                "Failed to load evidence index at %s; rebuilding from hollowed specs",
                index_path,
                exc_info=True,
            )
            rebuild_evidence_index(manager)
            return
    else:
        index = EvidenceIndex()

    index.add_spec(hollowed)
    index.save(index_path)
    logger.info("Updated evidence index at %s", index_path)


def rebuild_evidence_index(manager: WorkspaceManager) -> int:
    """Rebuild the evidence index from all hollowed specs in the workspace.

    Args:
        manager: Workspace manager

    Returns:
        Number of specs indexed
    """
    evidence_store_dir = manager.structure.workspace_dir / "evidence_store"
    index = EvidenceIndex()

    if not evidence_store_dir.exists():
        logger.info("No evidence store directory, nothing to rebuild")
        return 0

    count = 0
    for lib_dir in sorted(evidence_store_dir.iterdir()):
        if not lib_dir.is_dir():
            continue
        hollowed_path = lib_dir / "hollowed_spec.json"
        if not hollowed_path.exists():
            continue
        try:
            from spec_manager.schemas.hollowed_spec import HollowedSpec

            spec_data = json.loads(hollowed_path.read_text(encoding="utf-8"))
            spec = HollowedSpec.model_validate(spec_data)
            index.add_spec(spec)
            count += 1
            logger.info("Re-indexed %s", spec.lib_id)
        except Exception as exc:
            logger.warning("Failed to load hollowed spec from %s: %s", hollowed_path, exc)

    index_path = manager.structure.workspace_dir / "indexes" / "evidence_store_index.json"
    index.save(index_path)
    logger.info("Rebuilt evidence index with %d specs at %s", count, index_path)

    return count
