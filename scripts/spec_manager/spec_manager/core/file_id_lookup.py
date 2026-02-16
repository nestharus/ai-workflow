"""File ID lookup builder for mapping file identifiers to canonical IDs."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _add_lookup(
    lookup: dict[str, str],
    key: str,
    value: str,
    *,
    collisions: dict[str, set[str]],
) -> None:
    if not key:
        return
    if key in collisions:
        collisions[key].add(value)
        return
    existing = lookup.get(key)
    if existing is None:
        lookup[key] = value
        return
    if existing == value:
        return
    claims = collisions.setdefault(key, set())
    claims.update({existing, value})
    # Remove ambiguous aliases from the lookup so callers cannot resolve by accident.
    lookup.pop(key, None)


def build_file_id_lookup(
    file_manifest: dict[str, dict[str, str]], spec_snapshot_dir: Path | None = None
) -> dict[str, str]:
    """Build a lookup mapping various file identifiers to canonical file_id.

    Maps: file_id, relpath, resolved absolute path, filename, and stem.
    """
    lookup: dict[str, str] = {}
    collisions: dict[str, set[str]] = {}
    spec_snapshot_dir = spec_snapshot_dir or Path.cwd()
    for file_id, file_data in file_manifest.items():
        _add_lookup(lookup, file_id, file_id, collisions=collisions)
        relpath = file_data["relpath"]
        _add_lookup(lookup, relpath, file_id, collisions=collisions)
        _add_lookup(lookup, f"spec_snapshot/{relpath}", file_id, collisions=collisions)
        path = Path(relpath)
        if not path.is_absolute():
            path = spec_snapshot_dir / path
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = ""
        if resolved:
            _add_lookup(lookup, resolved, file_id, collisions=collisions)
        if path.name:
            _add_lookup(lookup, path.name, file_id, collisions=collisions)
        if path.stem:
            _add_lookup(lookup, path.stem, file_id, collisions=collisions)
    for key, claims in sorted(collisions.items()):
        logger.warning(
            "Ambiguous file lookup key discarded: %s claimed by %s",
            key,
            sorted(claims),
        )
    return lookup
