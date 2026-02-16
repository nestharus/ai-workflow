"""Spec execution scaffolding for iterative implementation.

This module provides the core data structures and logic for tracking
implementation progress against a decomposed spec.

Key concepts:
- Ledger: tracks status of each spec ID (pending/partial/complete)
- Hashes: detect spec edits since last execution
- Gaps: blocked needs that require spec refinement or dependency resolution
- Evidence: links implementation files to spec IDs
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Archive retention settings
# Archives are removed if they exceed the most recent ARCHIVE_RETENTION_COUNT
# OR if they are older than ARCHIVE_RETENTION_DAYS
ARCHIVE_RETENTION_COUNT = 10  # Keep only the 10 most recent archive files
ARCHIVE_RETENTION_DAYS = 30  # Or files older than 30 days


class SpecStatus(str, Enum):
    """Status of a spec ID in the execution ledger."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PARTIAL = "partial"
    COMPLETE = "complete"
    MODIFIED = "modified"  # Spec was edited since last run
    ORPHANED = "orphaned"  # Spec was deleted


@dataclass
class SpecEntry:
    """Ledger entry for a single spec ID."""

    spec_id: str
    status: SpecStatus = SpecStatus.PENDING
    hash: str = ""
    run_id: str | None = None
    files: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "hash": self.hash,
            "run_id": self.run_id,
            "files": self.files,
            "needs": self.needs,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, spec_id: str, data: dict[str, Any]) -> SpecEntry:
        return cls(
            spec_id=spec_id,
            status=SpecStatus(data.get("status", "pending")),
            hash=data.get("hash", ""),
            run_id=data.get("run_id"),
            files=data.get("files", []),
            needs=data.get("needs", []),
            notes=data.get("notes", ""),
        )


@dataclass
class Gap:
    """A blocked need during implementation."""

    id: str
    description: str
    blocking: list[str] = field(default_factory=list)  # Spec IDs blocked by this gap
    resolved_by: str | None = None  # Spec ID that resolves this gap
    investigated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "blocking": self.blocking,
            "resolved_by": self.resolved_by,
            "investigated": self.investigated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Gap:
        return cls(
            id=data["id"],
            description=data["description"],
            blocking=data.get("blocking", []),
            resolved_by=data.get("resolved_by"),
            investigated=data.get("investigated", False),
        )


@dataclass
class Ledger:
    """Execution ledger tracking implementation progress."""

    version: int = 1
    spec_hashes: dict[str, str] = field(default_factory=dict)
    entries: dict[str, SpecEntry] = field(default_factory=dict)
    gaps: list[Gap] = field(default_factory=list)
    alias_links: dict[str, str] = field(default_factory=dict)
    next_gap_id: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "spec_hashes": self.spec_hashes,
            "statuses": {k: v.to_dict() for k, v in self.entries.items()},
            "gaps": [g.to_dict() for g in self.gaps],
            "alias_links": self.alias_links,
            "next_gap_id": self.next_gap_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Ledger:
        ledger = cls(
            version=data.get("version", 1),
            spec_hashes=data.get("spec_hashes", {}),
            alias_links=data.get("alias_links", {}),
            next_gap_id=data.get("next_gap_id", 1),
        )
        for spec_id, entry_data in data.get("statuses", {}).items():
            ledger.entries[spec_id] = SpecEntry.from_dict(spec_id, entry_data)
        for gap_data in data.get("gaps", []):
            ledger.gaps.append(Gap.from_dict(gap_data))
        return ledger


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content."""
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


def load_ledger(workspace: Path) -> Ledger:
    """Load execution ledger from workspace."""
    ledger_path = workspace / "execution" / "ledger.json"
    if ledger_path.exists():
        return Ledger.from_dict(json.loads(ledger_path.read_text()))
    return Ledger()


def save_ledger(workspace: Path, ledger: Ledger) -> None:
    """Save execution ledger to workspace."""
    execution_dir = workspace / "execution"
    execution_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = execution_dir / "ledger.json"
    ledger_path.write_text(json.dumps(ledger.to_dict(), indent=2))


def save_gaps(workspace: Path, gaps: list[Gap]) -> None:
    """Save current gaps to workspace."""
    execution_dir = workspace / "execution"
    execution_dir.mkdir(parents=True, exist_ok=True)
    gaps_path = execution_dir / "gaps.json"
    gaps_path.write_text(json.dumps([g.to_dict() for g in gaps], indent=2))


def compute_spec_hashes(workspace: Path) -> dict[str, str]:
    """Compute hashes for all spec IDs from recomposed output.

    Returns a dict mapping spec_id -> content_hash.
    """
    hashes: dict[str, str] = {}

    # Load entities
    entities_dir = workspace / "entities"
    if entities_dir.exists():
        for entity_file in entities_dir.glob("*.md"):
            spec_id = entity_file.stem  # E-001, etc.
            hashes[spec_id] = compute_content_hash(entity_file.read_text())

    # Load relations
    relations_dir = workspace / "relations"
    if relations_dir.exists():
        for relation_file in relations_dir.glob("*.md"):
            spec_id = relation_file.stem  # R-001, etc.
            hashes[spec_id] = compute_content_hash(relation_file.read_text())

    # Load contexts
    contexts_dir = workspace / "context"
    if contexts_dir.exists():
        for context_file in contexts_dir.glob("*.md"):
            spec_id = context_file.stem  # C-001, etc.
            hashes[spec_id] = compute_content_hash(context_file.read_text())

    # Load orphans
    orphans_dir = workspace / "orphans"
    if orphans_dir.exists():
        for orphan_file in orphans_dir.glob("*.md"):
            spec_id = orphan_file.stem  # O-001, etc.
            hashes[spec_id] = compute_content_hash(orphan_file.read_text())

    # Load facts from tag-facts output
    facts_file = workspace / "facts.json"
    if facts_file.exists():
        facts = json.loads(facts_file.read_text())
        for fact_id, fact_data in facts.items():
            content = fact_data.get("text", "") if isinstance(fact_data, dict) else str(fact_data)
            hashes[fact_id] = compute_content_hash(content)

    return hashes


def detect_spec_changes(
    ledger: Ledger, current_hashes: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """Detect changes between ledger and current spec hashes.

    Returns:
        (new_ids, modified_ids, deleted_ids)
    """
    old_ids = set(ledger.spec_hashes.keys())
    new_ids_set = set(current_hashes.keys())

    new_ids = list(new_ids_set - old_ids)
    deleted_ids = list(old_ids - new_ids_set)
    modified_ids = [
        spec_id
        for spec_id in old_ids & new_ids_set
        if ledger.spec_hashes.get(spec_id) != current_hashes.get(spec_id)
    ]

    return sorted(new_ids), sorted(modified_ids), sorted(deleted_ids)


def get_runnable_ids(ledger: Ledger) -> list[str]:
    """Get spec IDs that are ready to be implemented.

    A spec ID is runnable if:
    - Status is PENDING or MODIFIED
    - Not blocked by an unresolved gap
    """
    blocked_by_gaps = set()
    for gap in ledger.gaps:
        if gap.resolved_by is None:
            blocked_by_gaps.update(gap.blocking)

    runnable = []
    for spec_id, entry in ledger.entries.items():
        if (
            entry.status in (SpecStatus.PENDING, SpecStatus.MODIFIED)
            and spec_id not in blocked_by_gaps
        ):
            runnable.append(spec_id)

    return sorted(runnable)


def generate_prompt_files(workspace: Path, runnable_ids: list[str]) -> dict[str, Path]:
    """Generate prompt files for plan/implement/review agents.

    Returns dict mapping prompt type to file path.
    """
    prompts_dir = workspace / "execution" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # Archive old prompts
    archive_dir = prompts_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for old_prompt in prompts_dir.glob("*.md"):
        archive_path = (
            archive_dir / f"{old_prompt.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )
        shutil.move(str(old_prompt), str(archive_path))

    # Clean up old archives beyond retention policy
    cleanup_old_archives(archive_dir)

    if not runnable_ids:
        return {}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Generate plan prompt
    plan_prompt = prompts_dir / f"plan_{timestamp}.md"
    plan_content = f"""# Spec Planning Prompt

## Target IDs
{chr(10).join(f"- {id}" for id in runnable_ids)}

## Task
Analyze the spec IDs above and create an implementation plan.

For each ID:
1. Read the spec content from the workspace
2. Identify dependencies on other IDs
3. Determine implementation order
4. Note any potential blockers

## Output
Write your plan to: {workspace}/execution/plans/plan_{timestamp}.md
"""
    plan_prompt.write_text(plan_content)

    # Generate implement prompt
    impl_prompt = prompts_dir / f"implement_{timestamp}.md"
    impl_content = f"""# Spec Implementation Prompt

## Target IDs
{chr(10).join(f"- {id}" for id in runnable_ids)}

## Task
Implement the spec IDs above.

For each ID:
1. Read the spec content
2. Implement the required functionality
3. Track which files you create/modify

## Evidence Map
After implementation, write an evidence map to:
{workspace}/execution/evidence/{timestamp}/implementation_map.json

Format:
```json
{{
  "run_id": "{timestamp}",
  "timestamp": "<ISO timestamp>",
  "implementations": [
    {{
      "spec_id": "<ID>",
      "status": "complete|partial",
      "files": ["<file1>", "<file2>"],
      "needs": ["<blocking need if partial>"],
      "notes": "<optional notes>"
    }}
  ],
  "gaps": [
    {{
      "description": "<what is missing>",
      "blocking": ["<spec IDs blocked>"],
      "investigated": false
    }}
  ]
}}
```
"""
    impl_prompt.write_text(impl_content)

    # Generate review prompt
    review_prompt = prompts_dir / f"review_{timestamp}.md"
    review_content = f"""# Spec Review Prompt

## Target IDs
{chr(10).join(f"- {id}" for id in runnable_ids)}

## Task
Review the implementation against the spec IDs.

For each ID:
1. Read the spec content
2. Check the implementation files
3. Verify all requirements are met
4. Note any gaps or issues

## Output
Write your review to: {workspace}/execution/reviews/review_{timestamp}.md
"""
    review_prompt.write_text(review_content)

    return {
        "plan": plan_prompt,
        "implement": impl_prompt,
        "review": review_prompt,
    }


def cleanup_old_archives(archive_dir: Path) -> None:
    """Remove old archived prompt files beyond retention policy.

    Keeps the most recent ARCHIVE_RETENTION_COUNT files and removes
    files older than ARCHIVE_RETENTION_DAYS.
    """
    if not archive_dir.exists():
        return

    archived_files = list(archive_dir.glob("*.md"))
    if not archived_files:
        return

    # Sort by modification time (newest first)
    archived_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    cutoff_time = datetime.now() - timedelta(days=ARCHIVE_RETENTION_DAYS)
    files_to_remove: list[Path] = []

    # Mark files beyond retention count for removal
    if len(archived_files) > ARCHIVE_RETENTION_COUNT:
        files_to_remove.extend(archived_files[ARCHIVE_RETENTION_COUNT:])

    # Mark files older than retention days for removal
    # Only check files within the retention slice to avoid redundant work
    for archived_file in archived_files[:ARCHIVE_RETENTION_COUNT]:
        try:
            mtime = datetime.fromtimestamp(archived_file.stat().st_mtime)
            if mtime < cutoff_time:
                files_to_remove.append(archived_file)
        except OSError:
            logger.warning(
                "Failed to get file stats for %s during archive cleanup",
                archived_file,
            )

    # Remove duplicate entries and delete files
    for file_to_remove in set(files_to_remove):
        try:
            file_to_remove.unlink(missing_ok=True)
        except OSError:
            logger.exception(
                "Failed to delete archive file %s during cleanup",
                file_to_remove,
            )


def ingest_evidence(workspace: Path, evidence_path: Path, ledger: Ledger) -> Ledger:
    """Ingest implementation evidence and update ledger."""
    evidence = json.loads(evidence_path.read_text())
    run_id = evidence.get("run_id", "unknown")
    valid_statuses = {"complete", "partial"}

    # Update entries from implementations
    for idx, impl in enumerate(evidence.get("implementations", []), start=1):
        spec_id = impl["spec_id"]
        status_str = impl.get("status")
        if status_str not in valid_statuses:
            raise ValueError(
                f"Invalid implementation status at index {idx} for {spec_id}: {status_str!r}. "
                f"Expected one of {sorted(valid_statuses)}."
            )

        if spec_id not in ledger.entries:
            ledger.entries[spec_id] = SpecEntry(spec_id=spec_id)

        entry = ledger.entries[spec_id]
        entry.status = SpecStatus.COMPLETE if status_str == "complete" else SpecStatus.PARTIAL
        entry.run_id = run_id
        entry.files = impl.get("files", [])
        entry.needs = impl.get("needs", [])
        entry.notes = impl.get("notes", "")

    # Add new gaps
    for gap_data in evidence.get("gaps", []):
        gap_id = f"gap_{ledger.next_gap_id:03d}"
        ledger.next_gap_id += 1
        ledger.gaps.append(
            Gap(
                id=gap_id,
                description=gap_data["description"],
                blocking=gap_data.get("blocking", []),
                investigated=gap_data.get("investigated", False),
            )
        )

    return ledger


def execute_spec(
    workspace: Path,
    repo: Path | None = None,
    ingest_path: Path | None = None,
) -> dict[str, Any]:
    """Main execute-spec entry point.

    Args:
        workspace: Decomposition workspace directory
        repo: Implementation repository root (optional)
        ingest_path: Path to evidence file to ingest (optional)

    Returns:
        Status dict with results
    """
    # Load or create ledger
    ledger = load_ledger(workspace)

    # Ingest evidence if provided
    if ingest_path and ingest_path.exists():
        ledger = ingest_evidence(workspace, ingest_path, ledger)
        save_ledger(workspace, ledger)
        save_gaps(workspace, ledger.gaps)
        return {
            "action": "ingest",
            "ingested": str(ingest_path),
            "gaps_count": len(ledger.gaps),
        }

    # Compute current spec hashes
    current_hashes = compute_spec_hashes(workspace)

    # Detect changes
    new_ids, modified_ids, deleted_ids = detect_spec_changes(ledger, current_hashes)

    # Update ledger with changes
    for spec_id in new_ids:
        ledger.entries[spec_id] = SpecEntry(
            spec_id=spec_id,
            status=SpecStatus.PENDING,
            hash=current_hashes[spec_id],
        )
        ledger.spec_hashes[spec_id] = current_hashes[spec_id]

    for spec_id in modified_ids:
        if spec_id in ledger.entries:
            ledger.entries[spec_id].status = SpecStatus.MODIFIED
        else:
            ledger.entries[spec_id] = SpecEntry(
                spec_id=spec_id,
                status=SpecStatus.MODIFIED,
                hash=current_hashes[spec_id],
            )
        ledger.spec_hashes[spec_id] = current_hashes[spec_id]

    for spec_id in deleted_ids:
        if spec_id in ledger.entries:
            ledger.entries[spec_id].status = SpecStatus.ORPHANED
        ledger.spec_hashes.pop(spec_id, None)

    # Get runnable IDs
    runnable_ids = get_runnable_ids(ledger)

    # Generate prompts
    prompts = generate_prompt_files(workspace, runnable_ids)

    # Save updated ledger
    save_ledger(workspace, ledger)
    save_gaps(workspace, ledger.gaps)

    return {
        "action": "prepare",
        "new_ids": new_ids,
        "modified_ids": modified_ids,
        "deleted_ids": deleted_ids,
        "runnable_ids": runnable_ids,
        "prompts": {k: str(v) for k, v in prompts.items()},
        "gaps_count": len([g for g in ledger.gaps if g.resolved_by is None]),
    }
