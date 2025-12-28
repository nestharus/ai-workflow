"""Fast file hashing for detecting changes between cycles.

Uses blake2b for fast hashing. Reads file list from stdin, outputs hashes to stdout.
Compare two hash files to check if files changed.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def _hash_file(path: Path) -> tuple[str, str | None]:
    """Hash a single file using blake2b.

    Args:
        path: Path to file.

    Returns:
        Tuple of (hex_digest, error). On success, error is None.
        On failure, hex_digest is empty string and error contains the message.
    """
    hasher = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest(), None
    except OSError as e:
        return "", str(e)


def file_hash_command(root: Path | None = None) -> int:
    """Hash files from stdin and output JSON to stdout.

    Reads file paths from stdin (one per line), computes hashes,
    and outputs JSON mapping file paths to their hashes.

    Args:
        root: Optional root directory for resolving relative paths.
              Defaults to current working directory.

    Returns:
        Exit code (0 for success).
    """
    if root is None:
        root = Path.cwd()

    hashes: dict[str, str] = {}
    seen_paths: set[str] = set()

    for line in sys.stdin:
        file_path = line.strip()
        if not file_path:
            continue

        path = Path(file_path)
        if not path.is_absolute():
            path = root / path

        # Resolve to absolute path for consistent deduplication
        resolved = path.resolve()
        resolved_key = str(resolved)

        # Skip if already processed (deduplication for both existing and non-existing paths)
        if resolved_key in seen_paths:
            continue
        seen_paths.add(resolved_key)

        if not resolved.exists():
            print(f"Notice: {file_path}: path does not exist", file=sys.stderr)
            continue

        file_hash, error = _hash_file(resolved)
        if file_hash:
            hashes[resolved_key] = file_hash
        elif error:
            print(f"Error: {file_path}: {error}", file=sys.stderr)

    print(json.dumps(hashes, indent=2, sort_keys=True))
    return 0


def file_hash_compare_command(file1: Path, file2: Path) -> int:
    """Compare two hash files and report if they differ.

    Args:
        file1: Path to first hash JSON file.
        file2: Path to second hash JSON file.

    Returns:
        Exit code: 0 if identical, 1 if different, 2 if error.
    """
    try:
        with open(file1) as f:
            hashes1: dict[str, str] = json.load(f)
        with open(file2) as f:
            hashes2: dict[str, str] = json.load(f)
    except FileNotFoundError as e:
        print(f"Error: File not found: {e.filename}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Error: I/O error reading file: {e}", file=sys.stderr)
        return 2

    if hashes1 == hashes2:
        print("IDENTICAL")
        return 0
    else:
        # Find what changed
        changed: list[str] = []
        added: list[str] = []
        deleted: list[str] = []

        all_files = set(hashes1.keys()) | set(hashes2.keys())
        for file_path in sorted(all_files):
            hash1 = hashes1.get(file_path)
            hash2 = hashes2.get(file_path)

            if hash1 is None and hash2 is not None:
                added.append(file_path)
            elif hash1 is not None and hash2 is None:
                deleted.append(file_path)
            elif hash1 != hash2:
                changed.append(file_path)

        result = {
            "status": "DIFFERENT",
            "changed": changed,
            "added": added,
            "deleted": deleted,
        }
        print(json.dumps(result, indent=2))
        return 1
