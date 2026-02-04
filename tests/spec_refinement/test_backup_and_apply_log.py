from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os

import pytest

from spec_manager.refinement.workflows import patch_utils


@pytest.fixture
def sample_patch() -> str:
    return (
        "diff --git a/test.py b/test.py\n"
        "index abc123..def456 100644\n"
        "--- a/test.py\n"
        "+++ b/test.py\n"
        "@@ -1,3 +1,3 @@\n"
        " def hello():\n"
        "-    print(\"old\")\n"
        "+    print(\"new\")\n"
        "     return True\n"
    )


def test_backup_creates_directory_structure(fs) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root / "dir/sub")
    file_path = repo_root / "dir/sub/file.txt"
    file_path.write_text("content", encoding="utf-8")

    backup_dir = repo_root / "backup"
    records = patch_utils.backup_files([file_path], backup_dir)

    assert len(records) == 1
    assert (backup_dir / "dir/sub/file.txt").exists()


def test_backup_computes_hashes(fs) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    file_path = repo_root / "file.txt"
    file_path.write_text("hash me", encoding="utf-8")

    backup_dir = repo_root / "backup"
    records = patch_utils.backup_files([file_path], backup_dir)

    expected = hashlib.sha256(b"hash me").hexdigest()
    assert records[0].original_hash == expected


def test_backup_preserves_metadata(fs) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    file_path = repo_root / "file.txt"
    file_path.write_text("content", encoding="utf-8")
    os.utime(file_path, (1234567890, 1234567890))

    backup_dir = repo_root / "backup"
    records = patch_utils.backup_files([file_path], backup_dir)

    backup_path = records[0].backup_path
    assert int(os.stat(backup_path).st_mtime) == int(os.stat(file_path).st_mtime)


def test_backup_handles_nested_paths(fs) -> None:
    repo_root = Path("/repo")
    nested = repo_root / "a/b/c/d"
    fs.create_dir(nested)
    file_path = nested / "file.txt"
    file_path.write_text("nested", encoding="utf-8")

    backup_dir = repo_root / "backup"
    records = patch_utils.backup_files([file_path], backup_dir)

    assert records
    assert (backup_dir / "a/b/c/d/file.txt").exists()


def test_backup_empty_list(fs) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    backup_dir = repo_root / "backup"
    records = patch_utils.backup_files([], backup_dir)
    assert records == []
    assert not backup_dir.exists()


def test_apply_creates_backup(sample_patch: str, fs, monkeypatch) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    (repo_root / "test.py").write_text(
        'def hello():\n    print("old")\n    return True\n',
        encoding="utf-8",
    )

    backup_dir = repo_root / "backup"

    monkeypatch.setattr(patch_utils, "apply_patch_with_git", lambda *args, **kwargs: (False, ""))

    result = patch_utils.apply_patch(
        patch_text=sample_patch,
        repo_root=repo_root,
        backup_dir=backup_dir,
        immutable_paths=patch_utils.IMMUTABLE_PATH_PATTERNS,
    )

    assert result["success"] is True
    assert (backup_dir / "test.py").exists()


def test_apply_records_log(sample_patch: str, fs, monkeypatch) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    (repo_root / "test.py").write_text(
        'def hello():\n    print("old")\n    return True\n',
        encoding="utf-8",
    )
    backup_dir = repo_root / "backup"

    monkeypatch.setattr(patch_utils, "apply_patch_with_git", lambda *args, **kwargs: (False, ""))

    result = patch_utils.apply_patch(
        patch_text=sample_patch,
        repo_root=repo_root,
        backup_dir=backup_dir,
        immutable_paths=patch_utils.IMMUTABLE_PATH_PATTERNS,
    )

    log_path = backup_dir / "apply_log.json"
    assert log_path.exists()
    log_data = json.loads(log_path.read_text(encoding="utf-8"))

    for key in [
        "timestamp",
        "patch_sha256",
        "applied_files",
        "backup_records",
        "method_used",
        "success",
        "error",
    ]:
        assert key in log_data
    assert log_data["patch_sha256"] == result["patch_sha256"]


def test_apply_computes_patch_hash(sample_patch: str, fs, monkeypatch) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    (repo_root / "test.py").write_text(
        'def hello():\n    print("old")\n    return True\n',
        encoding="utf-8",
    )
    backup_dir = repo_root / "backup"
    monkeypatch.setattr(patch_utils, "apply_patch_with_git", lambda *args, **kwargs: (False, ""))

    result = patch_utils.apply_patch(
        patch_text=sample_patch,
        repo_root=repo_root,
        backup_dir=backup_dir,
        immutable_paths=patch_utils.IMMUTABLE_PATH_PATTERNS,
    )

    expected = hashlib.sha256(sample_patch.encode("utf-8")).hexdigest()
    assert result["patch_sha256"] == expected


def test_apply_uses_git_first(sample_patch: str, fs, monkeypatch) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    (repo_root / "test.py").write_text(
        'def hello():\n    print("old")\n    return True\n',
        encoding="utf-8",
    )
    backup_dir = repo_root / "backup"
    called = {"manual": False}

    monkeypatch.setattr(patch_utils, "apply_patch_with_git", lambda *args, **kwargs: (True, ""))

    def _manual(*args, **kwargs):
        called["manual"] = True
        return True, ""

    monkeypatch.setattr(patch_utils, "apply_patch_manual", _manual)

    result = patch_utils.apply_patch(
        patch_text=sample_patch,
        repo_root=repo_root,
        backup_dir=backup_dir,
        immutable_paths=patch_utils.IMMUTABLE_PATH_PATTERNS,
    )

    assert result["method_used"] == "git"
    assert called["manual"] is False


def test_apply_falls_back_to_manual(sample_patch: str, fs, monkeypatch) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    (repo_root / "test.py").write_text(
        'def hello():\n    print("old")\n    return True\n',
        encoding="utf-8",
    )
    backup_dir = repo_root / "backup"

    monkeypatch.setattr(patch_utils, "apply_patch_with_git", lambda *args, **kwargs: (False, "git error"))
    monkeypatch.setattr(patch_utils, "apply_patch_manual", lambda *args, **kwargs: (True, ""))

    result = patch_utils.apply_patch(
        patch_text=sample_patch,
        repo_root=repo_root,
        backup_dir=backup_dir,
        immutable_paths=patch_utils.IMMUTABLE_PATH_PATTERNS,
    )

    assert result["method_used"] == "manual"
    assert result["success"] is True


def test_apply_rejects_invalid_patch(fs) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    backup_dir = repo_root / "backup"

    result = patch_utils.apply_patch(
        patch_text="",
        repo_root=repo_root,
        backup_dir=backup_dir,
        immutable_paths=patch_utils.IMMUTABLE_PATH_PATTERNS,
    )

    assert result["success"] is False
    assert not backup_dir.exists()


def test_apply_immutable_protection(fs) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    backup_dir = repo_root / "backup"

    patch_text = (
        "diff --git a/runs/run_001/spec_snapshot/file.txt "
        "b/runs/run_001/spec_snapshot/file.txt\n"
        "--- a/runs/run_001/spec_snapshot/file.txt\n"
        "+++ b/runs/run_001/spec_snapshot/file.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    result = patch_utils.apply_patch(
        patch_text=patch_text,
        repo_root=repo_root,
        backup_dir=backup_dir,
        immutable_paths=patch_utils.IMMUTABLE_PATH_PATTERNS,
    )

    assert result["success"] is False


def test_full_apply_workflow(sample_patch: str, fs, monkeypatch) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    original = 'def hello():\n    print("old")\n    return True\n'
    (repo_root / "test.py").write_text(original, encoding="utf-8")

    backup_dir = repo_root / "backup"

    monkeypatch.setattr(patch_utils, "apply_patch_with_git", lambda *args, **kwargs: (False, ""))

    result = patch_utils.apply_patch(
        patch_text=sample_patch,
        repo_root=repo_root,
        backup_dir=backup_dir,
        immutable_paths=patch_utils.IMMUTABLE_PATH_PATTERNS,
    )

    assert result["success"] is True
    assert (repo_root / "test.py").read_text(encoding="utf-8") != original
    assert (backup_dir / "test.py").exists()

    log_path = backup_dir / "apply_log.json"
    assert log_path.exists()

    backup_hash = patch_utils.compute_file_hash(backup_dir / "test.py")
    assert result["backup_records"][0]["original_hash"] == backup_hash
