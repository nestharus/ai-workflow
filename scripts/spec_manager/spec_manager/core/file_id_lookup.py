"""File ID lookup builder for mapping file identifiers to canonical IDs."""

from __future__ import annotations

from pathlib import Path


def _add_lookup(lookup: dict[str, str], key: str, value: str) -> None:
    if not key:
        return
    if key in lookup:
        return
    lookup[key] = value


def build_file_id_lookup(
    file_manifest: dict[str, dict[str, str]], spec_snapshot_dir: Path | None = None
) -> dict[str, str]:
    """Build a lookup mapping various file identifiers to canonical file_id.

    Maps: file_id, relpath, resolved absolute path, filename, and stem.
    """
    lookup: dict[str, str] = {}
    spec_snapshot_dir = spec_snapshot_dir or Path.cwd()
    for file_id, file_data in file_manifest.items():
        _add_lookup(lookup, file_id, file_id)
        relpath = file_data["relpath"]
        _add_lookup(lookup, relpath, file_id)
        _add_lookup(lookup, f"spec_snapshot/{relpath}", file_id)
        path = Path(relpath)
        if not path.is_absolute():
            path = spec_snapshot_dir / path
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = ""
        if resolved:
            _add_lookup(lookup, resolved, file_id)
        if path.name:
            _add_lookup(lookup, path.name, file_id)
        if path.stem:
            _add_lookup(lookup, path.stem, file_id)
    return lookup
