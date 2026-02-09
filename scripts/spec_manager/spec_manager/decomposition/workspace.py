"""Workspace management for spec decomposition.

This module is deliberately *mechanical*:

- It copies source material into a workspace without rewriting content.
- It records provenance so other steps can reliably point back to
  (source file, line number).

Reliability edge cases handled here:

- Multiple input files with the same filename (e.g., `spec.md`) no longer
  collide inside the workspace.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from spec_manager.decomposition.id_generator import save_id_map


def _spec_root(spec_path: Path) -> Path:
    """Determine a stable root for relative paths."""
    return spec_path.parent if spec_path.is_file() else spec_path


def _with_suffix_before_ext(path: Path, suffix: str) -> Path:
    """Insert suffix before the file extension.

    Example: docs/spec.md + _staged -> docs/spec_staged.md
    """
    if path.suffix:
        return path.with_name(f"{path.stem}{suffix}{path.suffix}")
    return path.with_name(f"{path.name}{suffix}")


def save_file_index(workspace: Path, index: dict) -> None:
    """Persist file index to workspace."""
    (workspace / "file_index.json").write_text(json.dumps(index, indent=2))


def load_file_index(workspace: Path) -> dict:
    """Load file index from workspace."""
    p = workspace / "file_index.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"spec_root": None, "files": []}


def resolve_source_to_discovery_staging(workspace: Path, source: str) -> Path | None:
    """Resolve a source file reference to a discovery staging file.

    `source` can be:
    - absolute source path
    - path relative to spec_root
    - a staged filename (ending with _staged.md)
    """
    p = Path(source)
    if p.exists() and p.name.endswith("_staged.md"):
        return p

    idx = load_file_index(workspace)
    spec_root = Path(idx.get("spec_root") or "")

    # Convert absolute -> relative if under spec_root
    rel_str: str | None = None
    try:
        if p.is_absolute() and spec_root and p.is_relative_to(spec_root):
            rel_str = str(p.relative_to(spec_root))
    except (ValueError, TypeError, PermissionError) as e:
        logging.debug("Path resolution failed for %s: %s", p, e)
        rel_str = None

    if rel_str is None:
        rel_str = source

    # Exact match against file index
    for entry in idx.get("files", []):
        if entry.get("relative") == rel_str or entry.get("source") == source:
            staged_rel = entry.get("discovery_staging")
            if staged_rel:
                candidate = workspace / staged_rel
                if candidate.exists():
                    return candidate

    # Fallback: try by basename (only if unique)
    candidates = list((workspace / "staging" / "discovery").rglob(p.name))
    if len(candidates) == 1:
        return candidates[0]

    return None


def resolve_source_to_original_copy(workspace: Path, source: str) -> Path | None:
    """Resolve a source file reference to the workspace original copy."""
    p = Path(source)
    idx = load_file_index(workspace)
    spec_root = Path(idx.get("spec_root") or "")

    rel_str: str | None = None
    try:
        if p.is_absolute() and spec_root and p.is_relative_to(spec_root):
            rel_str = str(p.relative_to(spec_root))
    except (ValueError, TypeError, PermissionError) as e:
        logging.debug("Path resolution failed for %s: %s", p, e)
        rel_str = None

    if rel_str is None:
        rel_str = source

    for entry in idx.get("files", []):
        if entry.get("relative") == rel_str or entry.get("source") == source:
            orig_rel = entry.get("original_copy")
            if orig_rel:
                candidate = workspace / orig_rel
                if candidate.exists():
                    return candidate

    candidates = list((workspace / "original").rglob(p.name))
    if len(candidates) == 1:
        return candidates[0]

    return None


def init_workspace(workspace: Path, spec_path: Path) -> None:
    """Initialize workspace directory structure.

    Creates:
        {workspace}/
        ├── staging/
        │   ├── discovery/     # Discovery staging (gets redacted)
        │   └── investigation/ # Investigation staging (fresh per entity)
        ├── original/          # Original source copies (never modified)
        ├── relation_staging/  # Relation snippets for decomposition
        ├── entities/          # Isolated entity documents
        ├── relations/         # Rich relation documents
        ├── context/           # Context documents
        ├── orphans/           # Orphan statements
        ├── output/            # Final generated output
        ├── entity_index.json  # Entity keywords for matching
        ├── state.json         # Workflow state
        └── id_map.json        # ID to source mapping
    """
    # Clean existing workspace
    if workspace.exists():
        shutil.rmtree(workspace)

    # Create directory structure
    (workspace / "staging" / "discovery").mkdir(parents=True)
    (workspace / "staging" / "investigation").mkdir(parents=True)
    (workspace / "original").mkdir()
    (workspace / "relation_staging").mkdir()
    (workspace / "entities").mkdir()
    (workspace / "relations").mkdir()
    (workspace / "context").mkdir()
    (workspace / "orphans").mkdir()
    (workspace / "output").mkdir()

    # Collect all files to stage
    spec_path = spec_path.resolve()
    root = _spec_root(spec_path)

    files_to_stage: list[Path] = []
    if spec_path.is_file():
        files_to_stage.append(spec_path)
    else:
        # Markdown is the only supported input type for now.
        files_to_stage.extend(sorted(p.resolve() for p in spec_path.rglob("*.md") if p.is_file()))

    # Build file index (avoids basename collisions by preserving relative paths)
    file_index = {
        "spec_root": str(root),
        "files": [],
    }

    for file_path in files_to_stage:
        rel = str(file_path.relative_to(root))

        original_rel = _with_suffix_before_ext(Path("original") / rel, "_original")
        staging_rel = _with_suffix_before_ext(Path("staging") / "discovery" / rel, "_staged")

        file_index["files"].append(
            {
                "source": str(file_path),
                "relative": rel,
                "original_copy": str(original_rel),
                "discovery_staging": str(staging_rel),
            }
        )

    save_file_index(workspace, file_index)

    # Initialize state with file tracking (store *relative* paths for stability)
    state = {
        "phase": "entity_discovery",
        "discovery_round": 0,
        "current_file": None,
        "current_entity": None,
        "files_completed": [],
        "files_remaining": [e["relative"] for e in file_index["files"]],
        "extracted_entities": [],
        "extracted_relations": [],
        "extracted_contexts": [],
        "snippets_marked": 0,
        "snippets_decomposed": 0,
        "entities_from_snippets": 0,
        "orphans_found": 0,
        "spec_path": str(spec_path),
        "spec_root": str(root),
    }
    save_state(workspace, state)

    # Initialize ID map
    save_id_map(workspace, {})

    # Initialize entity index
    entity_index_file = workspace / "entity_index.json"
    entity_index_file.write_text("{}")

    # Store original copies (never modified) and create discovery staging
    for entry in file_index["files"]:
        src = Path(entry["source"])
        rel = Path(entry["relative"])

        # Store original
        _store_original(src, rel, workspace)

        # Create discovery staging
        _stage_file(src, rel, workspace)


def _store_original(source: Path, relative: Path, workspace: Path) -> Path:
    """Store an original copy of the source file (never modified)."""
    original_rel = _with_suffix_before_ext(relative, "_original")
    original_path = workspace / "original" / original_rel
    original_path.parent.mkdir(parents=True, exist_ok=True)

    content = source.read_text()
    header = "\n".join(
        [
            f"<!-- ORIGINAL FROM (relative): {relative} -->",
            f"<!-- ORIGINAL FROM (absolute): {source} -->",
            "",
        ]
    )
    original_path.write_text(header + content)

    return original_path


def _stage_file(source: Path, relative: Path, workspace: Path) -> Path:
    """Create a discovery staging copy of a source file."""
    staged_rel = _with_suffix_before_ext(relative, "_staged")
    staged_path = workspace / "staging" / "discovery" / staged_rel
    staged_path.parent.mkdir(parents=True, exist_ok=True)

    content = source.read_text()
    header = "\n".join(
        [
            f"<!-- STAGED FROM (relative): {relative} -->",
            f"<!-- STAGED FROM (absolute): {source} -->",
            "",
        ]
    )
    staged_path.write_text(header + content)

    return staged_path


def create_investigation_staging(workspace: Path, entity_name: str) -> Path:
    """Create fresh investigation staging from originals for ONE entity.

    A separate investigation file is created per original source file. This keeps
    prompts small and preserves stable line numbers.

    Returns the investigation directory path.
    """
    investigation_root = workspace / "staging" / "investigation"
    investigation_root.mkdir(parents=True, exist_ok=True)

    safe_name = entity_name.replace(" ", "_").replace("/", "_")
    entity_dir = investigation_root / safe_name
    if entity_dir.exists():
        shutil.rmtree(entity_dir)
    entity_dir.mkdir(parents=True, exist_ok=True)

    # Copy from original (not from discovery staging)
    for original_file in sorted((workspace / "original").rglob("*_original.md")):
        content = original_file.read_text()

        header = "\n".join(
            [
                f"<!-- INVESTIGATION STAGING FOR: {entity_name} -->",
                f"<!-- SOURCE: {original_file} -->",
                "",
            ]
        )

        # Strip the original header block (all leading HTML comments + first blank line)
        lines = content.split("\n")
        start_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("<!--"):
                continue
            if line.strip() == "":
                start_idx = i + 1
                break
            start_idx = i
            break

        body = "\n".join(lines[start_idx:])

        # Preserve original relative path structure under the entity folder
        rel_path = original_file.relative_to(workspace / "original")
        rel_path = rel_path.with_name(rel_path.name.replace("_original.md", "_investigation.md"))
        investigation_path = entity_dir / rel_path
        investigation_path.parent.mkdir(parents=True, exist_ok=True)
        investigation_path.write_text(header + body)

    return entity_dir


def resolve_original_copy(workspace: Path, original_file: str | Path) -> Path | None:
    """Resolve an original source file path to its workspace-stored original copy.

    Delegates to resolve_source_to_original_copy which uses the file_index.
    """
    return resolve_source_to_original_copy(workspace, str(original_file))


def resolve_discovery_staging(workspace: Path, original_file: str | Path) -> Path | None:
    """Resolve an original source file path to its discovery staging file.

    Delegates to resolve_source_to_discovery_staging which uses the file_index.
    """
    return resolve_source_to_discovery_staging(workspace, str(original_file))


def list_discovery_staging_files(workspace: Path) -> list[Path]:
    """List all discovery staging files in deterministic order."""
    discovery_dir = workspace / "staging" / "discovery"
    return sorted(discovery_dir.rglob("*_staged.md"))


def load_state(workspace: Path) -> dict:
    """Load workflow state from state.json."""
    state_file = workspace / "state.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}


def save_state(workspace: Path, state: dict) -> None:
    """Save workflow state to state.json."""
    state_file = workspace / "state.json"
    state_file.write_text(json.dumps(state, indent=2))
