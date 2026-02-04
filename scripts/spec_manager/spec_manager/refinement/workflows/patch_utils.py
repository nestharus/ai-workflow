r"""Patch validation and application utilities for task implementation.

Provides deterministic patch parsing, validation, backup, and application
for Phase 10 task execution. Supports unified diff format with git apply
as the preferred method and pure-Python fallback.

Core invariants:
- All patches are validated before application
- Immutable paths (spec_snapshot/, manifest/) are protected
- Every applied patch has a backup and audit trail
- File hashes use sha256 for consistency

Example usage:
    >>> patch_text = "diff --git a/file.py b/file.py\n..."
    >>> result = apply_patch(
    ...     patch_text=patch_text,
    ...     repo_root=Path("/repo"),
    ...     backup_dir=Path("/repo/runs/run_001/tasks/TASK-0001/backup"),
    ...     immutable_paths=["runs/*/spec_snapshot/", "runs/*/manifest/"]
    ... )
    >>> if result["success"]:
    ...     print(f"Applied {len(result['applied_files'])} files")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

logger = logging.getLogger(__name__)

IMMUTABLE_PATH_PATTERNS = [
    "runs/*/spec_snapshot/**",
    "runs/*/manifest/**",
]

PATCH_HEADER_PATTERN = re.compile(r"^diff --git a/(.*) b/(.*)$", re.MULTILINE)
FILE_HEADER_PATTERN = re.compile(r"^---\s+(.*)$\n^\+\+\+\s+(.*)$", re.MULTILINE)
HUNK_HEADER_PATTERN = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")
BINARY_PATCH_PATTERN = re.compile(r"^Binary files .* differ$", re.MULTILINE)

_WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


class PatchValidationError(Exception):
    """Error raised when a patch fails validation or parsing."""

    def __init__(self, error_type: str, details: dict[str, Any]) -> None:
        """Initialize the validation error."""
        self.error_type = error_type
        self.details = details
        message = details.get("message") or error_type
        super().__init__(message)


@dataclass
class PatchHunk:
    """Represents a single hunk within a patch file."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


@dataclass
class PatchFile:
    """Represents a file change in a patch."""

    old_path: str
    new_path: str
    hunks: list[PatchHunk]


@dataclass
class ParsedPatch:
    """Parsed patch containing all file changes."""

    files: list[PatchFile]


@dataclass
class BackupRecord:
    """Record of a backed-up file for auditing."""

    path: Path
    original_hash: str
    backup_path: Path


@dataclass
class ApplyLogEntry:
    """Audit log entry for a patch application."""

    timestamp: str
    files_changed: list[str]
    patch_hash: str
    backup_records: list[BackupRecord]


def parse_unified_diff(patch_text: str) -> ParsedPatch:
    """Parse a unified diff into structured patch objects.

    Args:
        patch_text: Patch text in unified diff format.

    Returns:
        ParsedPatch containing file and hunk metadata.

    Raises:
        PatchValidationError: If the patch format is invalid.
    """
    if not patch_text.strip():
        raise _invalid_format("Patch text is empty")

    lines = patch_text.splitlines()
    parsed_files: list[PatchFile] = []
    current_file: PatchFile | None = None
    current_hunk: PatchHunk | None = None
    binary_file_ids: set[int] = set()

    for line_number, line in enumerate(lines, start=1):
        match = PATCH_HEADER_PATTERN.match(line)
        if match:
            old_path, new_path = match.groups()
            current_file = PatchFile(old_path=old_path, new_path=new_path, hunks=[])
            parsed_files.append(current_file)
            current_hunk = None
            continue
        if line.startswith("diff --git "):
            raise _invalid_format("Invalid diff header", line_number=line_number)

        if current_file is None:
            if not line.strip():
                continue
            raise _invalid_format("Unexpected content before diff header", line_number)

        if line.startswith("--- "):
            old_marker = line[4:].strip()
            if old_marker.startswith("a/"):
                old_marker = old_marker[2:]
            current_file.old_path = old_marker
            continue
        if line.startswith("+++ "):
            new_marker = line[4:].strip()
            if new_marker.startswith("b/"):
                new_marker = new_marker[2:]
            current_file.new_path = new_marker
            continue

        hunk_match = HUNK_HEADER_PATTERN.match(line)
        if hunk_match:
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2) or "1")
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or "1")
            current_hunk = PatchHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=[],
            )
            current_file.hunks.append(current_hunk)
            continue

        if line.startswith("\\ No newline at end of file"):
            continue
        if BINARY_PATCH_PATTERN.match(line):
            binary_file_ids.add(id(current_file))
            continue

        if line.startswith(
            (
                "index ",
                "new file mode ",
                "deleted file mode ",
                "similarity index ",
                "rename from ",
                "rename to ",
                "old mode ",
                "new mode ",
            )
        ):
            continue

        if line and line[0] in {" ", "+", "-"}:
            if current_hunk is None:
                raise _invalid_format("Patch line outside hunk", line_number=line_number)
            current_hunk.lines.append(line)
            continue

        if not line.strip():
            continue

        raise _invalid_format("Unrecognized patch content", line_number=line_number)

    if not parsed_files:
        raise _invalid_format("No diff headers found")

    for patch_file in parsed_files:
        if not patch_file.hunks and id(patch_file) not in binary_file_ids:
            raise _invalid_format(
                "Patch file contains no hunks",
                path=_select_patch_path(patch_file),
            )

    return ParsedPatch(files=parsed_files)


def validate_patch(
    patch_text: str,
    repo_root: Path,
    immutable_paths: list[str],
) -> tuple[bool, list[dict[str, Any]]]:
    """Validate patch structure and target paths.

    Args:
        patch_text: Unified diff patch text.
        repo_root: Repository root path.
        immutable_paths: Glob patterns for paths that must not be patched.

    Returns:
        Tuple of (is_valid, errors). Errors are structured dictionaries.
    """
    errors: list[dict[str, Any]] = []
    path_line_numbers = _collect_path_line_numbers(patch_text)

    _append_binary_patch_errors(patch_text, errors)

    try:
        parsed = parse_unified_diff(patch_text)
    except PatchValidationError as exc:
        errors.append(exc.details)
        return False, errors

    logger.info("Validating patch (files=%d)", len(parsed.files))
    _validate_parsed_patch(parsed, repo_root, immutable_paths, path_line_numbers, errors)
    logger.info("Validation completed (errors=%d)", len(errors))

    return not errors, errors


def apply_patch_with_git(
    patch_text: str,
    repo_root: Path,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Apply a patch using git apply.

    Args:
        patch_text: Unified diff patch text.
        repo_root: Repository root.
        dry_run: If True, run git apply --check.

    Returns:
        Tuple of (success, error_message).
    """
    repo_root = repo_root.resolve(strict=False)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=repo_root,
            prefix="patch_",
            suffix=".diff",
        ) as handle:
            handle.write(patch_text)
            temp_path = Path(handle.name)
    except OSError as exc:
        return False, str(exc)

    try:
        cmd = ["git", "apply"]
        if dry_run:
            cmd.append("--check")
        cmd.append(str(temp_path))
        result = _run_git(cmd, cwd=repo_root)
        if result is None:
            return False, "git is not available"
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "git apply failed"
            return False, message
        return True, ""
    finally:
        with suppress(OSError):
            temp_path.unlink()


def apply_patch_manual(patch_text: str, repo_root: Path) -> tuple[bool, str]:
    """Apply a unified diff patch manually without git.

    Args:
        patch_text: Unified diff patch text.
        repo_root: Repository root.

    Returns:
        Tuple of (success, error_message).
    """
    try:
        parsed = parse_unified_diff(patch_text)
    except PatchValidationError as exc:
        return False, exc.details.get("message", "invalid patch")

    for patch_file in parsed.files:
        target_path, is_new, is_delete = _resolve_target_path(patch_file, repo_root)
        logger.debug("Applying patch to %s", target_path)

        content, line_ending, ends_with_newline = _read_file_for_patch(target_path)
        file_lines = content.splitlines()

        for hunk in patch_file.hunks:
            logger.debug(
                "Applying hunk (old_start=%d, new_start=%d)",
                hunk.old_start,
                hunk.new_start,
            )
            success, message = _apply_hunk(file_lines, hunk)
            if not success:
                return False, message

        if is_delete:
            if target_path.exists():
                target_path.unlink()
            continue

        if is_new and not ends_with_newline:
            ends_with_newline = True

        target_path.parent.mkdir(parents=True, exist_ok=True)
        updated = line_ending.join(file_lines)
        if file_lines and ends_with_newline:
            updated += line_ending
        target_path.write_text(updated, encoding="utf-8")

    return True, ""


def backup_files(files: list[Path], backup_dir: Path) -> list[BackupRecord]:
    """Backup files to a backup directory, preserving relative structure."""
    if not files:
        return []

    backup_dir.mkdir(parents=True, exist_ok=True)
    records: list[BackupRecord] = []
    seen: set[str] = set()
    total_size = 0

    for path in files:
        resolved = path.resolve(strict=False)
        resolved_key = str(resolved)
        if resolved_key in seen:
            continue
        seen.add(resolved_key)

        if not resolved.exists():
            continue

        file_hash = compute_file_hash(resolved)
        relative_path = _relative_backup_path(path, backup_dir)
        backup_path = backup_dir / relative_path
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, backup_path)
        total_size += resolved.stat().st_size
        records.append(BackupRecord(path=path, original_hash=file_hash, backup_path=backup_path))
        logger.debug("Backing up file: %s (hash=%s)", path, file_hash)

    logger.info("Backup created (files=%d, total_bytes=%d)", len(records), total_size)
    return records


def apply_patch(
    patch_text: str,
    repo_root: Path,
    backup_dir: Path,
    immutable_paths: list[str],
) -> dict[str, Any]:
    """Validate, backup, and apply a patch.

    Returns:
        Dictionary containing apply log data and success status.
    """
    patch_hash = hashlib.sha256(patch_text.encode("utf-8")).hexdigest()
    timestamp = datetime.now(UTC).isoformat()

    try:
        parsed = parse_unified_diff(patch_text)
    except PatchValidationError as exc:
        return {
            "timestamp": timestamp,
            "patch_sha256": patch_hash,
            "applied_files": [],
            "backup_records": [],
            "method_used": None,
            "success": False,
            "error": exc.details.get("message", "invalid patch"),
        }

    errors: list[dict[str, Any]] = []
    _append_binary_patch_errors(patch_text, errors)
    path_line_numbers = _collect_path_line_numbers(patch_text)
    _validate_parsed_patch(parsed, repo_root, immutable_paths, path_line_numbers, errors)
    if errors:
        return {
            "timestamp": timestamp,
            "patch_sha256": patch_hash,
            "applied_files": [],
            "backup_records": [],
            "method_used": None,
            "success": False,
            "error": json.dumps(errors, indent=2),
        }

    touched_paths = _extract_paths_from_parsed(parsed)
    applied_files = [path.as_posix() for path in touched_paths]

    existing_files = [repo_root / path for path in touched_paths if (repo_root / path).exists()]
    logger.info("Creating backups for %d files", len(existing_files))
    backup_records = backup_files(existing_files, backup_dir)

    start = time.perf_counter()
    success, error = apply_patch_with_git(patch_text, repo_root)
    method_used = "git"
    if not success:
        logger.info("git apply failed, falling back to manual: %s", error)
        success, error = apply_patch_manual(patch_text, repo_root)
        method_used = "manual"
    elapsed_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "Patch application completed (method=%s, success=%s, latency_ms=%.2f)",
        method_used,
        success,
        elapsed_ms,
    )

    apply_log = {
        "timestamp": timestamp,
        "patch_sha256": patch_hash,
        "applied_files": applied_files,
        "backup_records": [
            {
                "path": str(record.path),
                "original_hash": record.original_hash,
                "backup_path": str(record.backup_path),
            }
            for record in backup_records
        ],
        "method_used": method_used,
        "success": success,
        "error": error or None,
    }

    backup_dir.mkdir(parents=True, exist_ok=True)
    log_path = backup_dir / "apply_log.json"
    log_path.write_text(json.dumps(apply_log, indent=2, sort_keys=True), encoding="utf-8")

    return apply_log


def extract_touched_paths(patch_text: str) -> list[str]:
    """Extract all file paths mentioned in a patch."""
    parsed = parse_unified_diff(patch_text)
    return [path.as_posix() for path in _extract_paths_from_parsed(parsed)]


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(65536):
                hasher.update(chunk)
    except OSError:
        return ""
    digest = hasher.hexdigest()
    logger.debug("Computed hash for %s: %s", path, digest)
    return digest


def _run_git(
    args: list[str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None


def _invalid_format(
    message: str,
    line_number: int | None = None,
    path: str | None = None,
) -> PatchValidationError:
    return PatchValidationError(
        "invalid_format",
        _build_error("invalid_format", message, path=path, line_number=line_number),
    )


def _build_error(
    error_type: str,
    message: str,
    path: str | None = None,
    line_number: int | None = None,
) -> dict[str, Any]:
    return {
        "type": error_type,
        "message": message,
        "path": path,
        "line_number": line_number,
    }


def _collect_path_line_numbers(patch_text: str) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for line_number, line in enumerate(patch_text.splitlines(), start=1):
        header_match = PATCH_HEADER_PATTERN.match(line)
        if header_match:
            old_path, new_path = header_match.groups()
            mapping.setdefault(old_path, line_number)
            mapping.setdefault(new_path, line_number)
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("a/") or path.startswith("b/"):
                path = path[2:]
            mapping.setdefault(path, line_number)
    return mapping


def _validate_parsed_patch(
    parsed: ParsedPatch,
    repo_root: Path,
    immutable_paths: list[str],
    path_line_numbers: dict[str, int],
    errors: list[dict[str, Any]],
) -> None:
    repo_root_resolved = repo_root.resolve(strict=False)

    for patch_file in parsed.files:
        for path_str in _paths_for_validation(patch_file):
            line_number = path_line_numbers.get(path_str)
            if _is_absolute_path(path_str):
                errors.append(
                    _build_error(
                        "absolute_path",
                        "Patch contains absolute path",
                        path=path_str,
                        line_number=line_number,
                    )
                )

            normalized_path = path_str.replace("\\", "/")
            if _path_matches_immutable(normalized_path, immutable_paths):
                errors.append(
                    _build_error(
                        "immutable_path",
                        "Patch modifies immutable path",
                        path=path_str,
                        line_number=line_number,
                    )
                )

            resolved = (repo_root_resolved / normalized_path).resolve(strict=False)
            if not _is_within_repo(resolved, repo_root_resolved):
                errors.append(
                    _build_error(
                        "outside_repo",
                        "Patch path resolves outside repository",
                        path=path_str,
                        line_number=line_number,
                    )
                )


def _paths_for_validation(patch_file: PatchFile) -> list[str]:
    paths: list[str] = []
    if patch_file.old_path and patch_file.old_path != "/dev/null":
        paths.append(patch_file.old_path)
    if patch_file.new_path and patch_file.new_path != "/dev/null":
        paths.append(patch_file.new_path)
    return _dedupe_preserve_order(paths)


def _is_absolute_path(path_str: str) -> bool:
    return Path(path_str).is_absolute() or bool(_WINDOWS_ABSOLUTE_PATTERN.match(path_str))


def _path_matches_immutable(path_str: str, patterns: list[str]) -> bool:
    pure_path = PurePosixPath(path_str)
    return any(pure_path.match(pattern) for pattern in patterns)


def _is_within_repo(path: Path, repo_root: Path) -> bool:
    try:
        path.relative_to(repo_root)
        return True
    except ValueError:
        return False


def _select_patch_path(patch_file: PatchFile) -> str:
    if patch_file.new_path and patch_file.new_path != "/dev/null":
        return patch_file.new_path
    return patch_file.old_path


def _extract_paths_from_parsed(parsed: ParsedPatch) -> list[Path]:
    paths: list[Path] = []
    for patch_file in parsed.files:
        for path_str in _paths_for_validation(patch_file):
            paths.append(Path(path_str))
    return _dedupe_path_list(paths)


def _resolve_target_path(
    patch_file: PatchFile,
    repo_root: Path,
) -> tuple[Path, bool, bool]:
    is_new = patch_file.old_path == "/dev/null"
    is_delete = patch_file.new_path == "/dev/null"
    target = patch_file.old_path if is_delete else patch_file.new_path
    return repo_root / target, is_new, is_delete


def _read_file_for_patch(path: Path) -> tuple[str, str, bool]:
    if not path.exists():
        return "", "\n", False
    with open(path, encoding="utf-8", errors="replace", newline="") as handle:
        content = handle.read()
    line_ending = "\n"
    if "\r\n" in content:
        line_ending = "\r\n"
    elif "\r" in content:
        line_ending = "\r"
    ends_with_newline = content.endswith(("\n", "\r"))
    return content, line_ending, ends_with_newline


def _apply_hunk(file_lines: list[str], hunk: PatchHunk) -> tuple[bool, str]:
    old_lines = [line[1:] for line in hunk.lines if line.startswith((" ", "-"))]
    new_lines = [line[1:] for line in hunk.lines if line.startswith((" ", "+"))]

    expected_index = max(hunk.old_start - 1, 0)
    match_index = _find_hunk_index(file_lines, old_lines, expected_index)
    if match_index is None:
        return False, "context mismatch applying hunk"

    file_lines[match_index : match_index + len(old_lines)] = new_lines
    return True, ""


def _find_hunk_index(
    file_lines: list[str],
    old_lines: list[str],
    expected_index: int,
) -> int | None:
    if not old_lines:
        return min(expected_index, len(file_lines))

    if file_lines[expected_index : expected_index + len(old_lines)] == old_lines:
        return expected_index

    matches: list[int] = []
    last_start = len(file_lines) - len(old_lines)
    for idx in range(0, last_start + 1):
        if file_lines[idx : idx + len(old_lines)] == old_lines:
            matches.append(idx)

    if not matches:
        return None

    return min(matches, key=lambda idx: abs(idx - expected_index))


def _append_binary_patch_errors(patch_text: str, errors: list[dict[str, Any]]) -> None:
    for line_number, line in enumerate(patch_text.splitlines(), start=1):
        if BINARY_PATCH_PATTERN.match(line):
            errors.append(
                _build_error(
                    "binary_patch",
                    "Binary patch detected",
                    path=None,
                    line_number=line_number,
                )
            )


def _relative_backup_path(path: Path, backup_dir: Path) -> Path:
    if not path.is_absolute():
        return path

    try:
        common_root = Path(os.path.commonpath([str(backup_dir), str(path)]))
        return path.relative_to(common_root)
    except (ValueError, OSError):
        return Path(path.name)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dedupe_path_list(items: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for item in items:
        key = item.as_posix()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


__all__ = [
    "ApplyLogEntry",
    "BackupRecord",
    "ParsedPatch",
    "PatchFile",
    "PatchHunk",
    "PatchValidationError",
    "apply_patch",
    "apply_patch_manual",
    "apply_patch_with_git",
    "backup_files",
    "compute_file_hash",
    "extract_touched_paths",
    "parse_unified_diff",
    "validate_patch",
]
