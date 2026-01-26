"""Workspace management for spec decomposition."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from scripts.spec_decomposition.id_generator import save_id_map


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
    spec_root = spec_path if spec_path.is_dir() else spec_path.parent

    files_to_stage: list[Path] = []
    if spec_path.is_file():
        files_to_stage.append(spec_path)
    else:
        files_to_stage.extend(sorted(p.resolve() for p in spec_path.rglob("*.md") if p.is_file()))

    # Build a stable mapping from original file paths -> workspace basenames.
    # This avoids collisions when multiple files share the same stem.
    file_map: dict[str, str] = {}
    for file_path in files_to_stage:
        file_map[str(file_path)] = _safe_workspace_basename(file_path, spec_root)

    # Initialize state with file tracking
    state = {
        "phase": "entity_discovery",
        "discovery_round": 0,
        "current_file": None,
        "current_entity": None,
        "files_completed": [],
        "files_remaining": [str(f) for f in files_to_stage],
        "extracted_entities": [],
        "extracted_relations": [],
        "extracted_contexts": [],
        "snippets_marked": 0,
        "snippets_decomposed": 0,
        "entities_from_snippets": 0,
        "orphans_found": 0,
        "spec_path": str(spec_path),
        "spec_root": str(spec_root),
        "file_map": file_map,
    }
    save_state(workspace, state)

    # Initialize ID map
    save_id_map(workspace, {})

    # Initialize entity index
    entity_index_file = workspace / "entity_index.json"
    entity_index_file.write_text("{}")

    # Store original copies (never modified) and create discovery staging
    for file_path in files_to_stage:
        basename = file_map[str(file_path)]
        # Store original
        _store_original(file_path, workspace / "original", basename)
        # Create discovery staging copy
        _stage_file(file_path, workspace / "staging" / "discovery", basename)


def _safe_workspace_basename(source: Path, spec_root: Path) -> str:
    """Create a workspace-safe, collision-resistant basename for a source file."""
    try:
        rel = source.relative_to(spec_root)
        rel_str = rel.as_posix()
    except ValueError:
        rel_str = source.name

    # Drop the suffix if present.
    if rel_str.lower().endswith(".md"):
        rel_str = rel_str[:-3]

    safe = rel_str.replace("/", "__").replace("\\", "__")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe)
    safe = safe.strip("._-")
    return safe or source.stem


def _store_original(source: Path, original_dir: Path, basename: str) -> Path:
    """Store an original copy of the source file (never modified).

    Args:
        source: Original source file path
        original_dir: Directory to store original

    Returns:
        Path to the stored original
    """
    original_name = f"{basename}_original.md"
    original_path = original_dir / original_name

    content = source.read_text()
    header = f"<!-- ORIGINAL FROM: {source} -->\n\n"
    original_path.write_text(header + content)

    return original_path


def _stage_file(source: Path, staging_dir: Path, basename: str) -> Path:
    """Create a staging copy of a file with line numbers tracked.

    The staging file has the same content but with a comment at the top
    indicating it's a staged copy for ID embedding.
    """
    staged_name = f"{basename}_staged.md"
    staged_path = staging_dir / staged_name

    content = source.read_text()
    header = f"<!-- STAGED FROM: {source} -->\n\n"
    staged_path.write_text(header + content)

    return staged_path


def create_investigation_staging(workspace: Path, entity_name: str) -> Path:
    """Create fresh investigation staging from original for an entity.

    Args:
        workspace: Workspace directory
        entity_name: Entity being investigated

    Returns:
        Path to the investigation staging file
    """
    investigation_dir = workspace / "staging" / "investigation"
    investigation_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize entity name for filename
    safe_name = entity_name.replace(" ", "_").replace("/", "_")

    # Combine all originals into one investigation staging file so the agent can
    # operate on a single numbered line space, while we still retain a mapping
    # back to (file, line, text).
    original_dir = workspace / "original"
    original_files = sorted(original_dir.glob("*_original.md"))

    combined_path = investigation_dir / f"{safe_name}_combined_investigation.md"
    map_path = investigation_dir / f"{safe_name}_combined_map.json"

    combined_lines: list[str] = [
        f"<!-- INVESTIGATION STAGING FOR: {entity_name} -->",
        f"<!-- COMBINED SOURCES: {len(original_files)} -->",
        "",
    ]

    # Line numbers in agent output are 1-indexed and count lines after this header.
    combined_content_line_no = 0

    # Map: combined_line_number -> {file, line, text}
    line_map: dict[str, dict] = {}
    sources: list[dict] = []

    for original_file in original_files:
        raw_lines = original_file.read_text().split("\n")

        # Extract the original file path from the stored header.
        original_source = None
        if raw_lines and raw_lines[0].startswith("<!-- ORIGINAL FROM:"):
            original_source = raw_lines[0].split("ORIGINAL FROM:", 1)[1].strip().rstrip("-->").strip()

        # Strip the original header (comment + blank line) from the stored copy.
        if raw_lines and raw_lines[0].startswith("<!-- ORIGINAL FROM:"):
            content_lines = raw_lines[2:]
        else:
            content_lines = raw_lines

        sources.append({
            "workspace_original": str(original_file),
            "original_source": original_source,
        })

        # Internal marker so humans can see boundaries; agents should not treat as content.
        combined_lines.append(f"<!-- FILE: {original_source or original_file.name} -->")
        combined_content_line_no += 1
        combined_lines.append("")
        combined_content_line_no += 1

        source_line_no = 0
        for line in content_lines:
            combined_lines.append(line)
            combined_content_line_no += 1
            source_line_no += 1
            if original_source is not None:
                line_map[str(combined_content_line_no)] = {
                    "file": original_source,
                    "line": source_line_no,
                    "text": line,
                }

    combined_path.write_text("\n".join(combined_lines))

    map_path.write_text(json.dumps({
        "entity": entity_name,
        "combined_file": str(combined_path),
        "sources": sources,
        "line_map": line_map,
    }, indent=2))

    # Track the latest investigation staging in state for tooling that needs it.
    state = load_state(workspace)
    state.setdefault("investigation_staging", {})[safe_name] = {
        "entity": entity_name,
        "combined_file": str(combined_path),
        "map_file": str(map_path),
    }
    save_state(workspace, state)

    return combined_path


def resolve_original_copy(workspace: Path, original_file: str | Path) -> Path | None:
    """Resolve an original source file path to its workspace-stored original copy."""
    state = load_state(workspace)
    file_map: dict[str, str] = state.get("file_map", {})
    key = str(Path(original_file).resolve())

    basename = file_map.get(key) or file_map.get(str(original_file))
    if not basename:
        # Fallback: try to match by filename if unambiguous.
        target_name = Path(original_file).name
        matches = [bn for path, bn in file_map.items() if Path(path).name == target_name]
        if len(matches) == 1:
            basename = matches[0]

    if not basename:
        return None

    return workspace / "original" / f"{basename}_original.md"


def resolve_discovery_staging(workspace: Path, original_file: str | Path) -> Path | None:
    """Resolve an original source file path to its discovery staging file."""
    state = load_state(workspace)
    file_map: dict[str, str] = state.get("file_map", {})
    key = str(Path(original_file).resolve())

    basename = file_map.get(key) or file_map.get(str(original_file))
    if not basename:
        target_name = Path(original_file).name
        matches = [bn for path, bn in file_map.items() if Path(path).name == target_name]
        if len(matches) == 1:
            basename = matches[0]

    if not basename:
        return None

    return workspace / "staging" / "discovery" / f"{basename}_staged.md"


def list_discovery_staging_files(workspace: Path) -> list[Path]:
    """List all discovery staging files in deterministic order."""
    discovery_dir = workspace / "staging" / "discovery"
    return sorted(discovery_dir.glob("*_staged.md"))


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
