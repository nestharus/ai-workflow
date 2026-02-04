from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from spec_manager.refinement.workflows import patch_utils


@pytest.fixture
def sample_patch() -> str:
    """Simple unified diff for testing."""
    return (
        "diff --git a/test.py b/test.py\n"
        "index abc123..def456 100644\n"
        "--- a/test.py\n"
        "+++ b/test.py\n"
        "@@ -1,3 +1,3 @@\n"
        " def hello():\n"
        '-    print("old")\n'
        '+    print("new")\n'
        "     return True\n"
    )


@pytest.fixture
def repo_with_files(fs) -> Path:
    """Fake repository with test files."""
    repo = Path("/repo")
    fs.create_dir(repo)
    (repo / "test.py").write_text(
        'def hello():\n    print("old")\n    return True\n',
        encoding="utf-8",
    )
    return repo


def test_parse_simple_patch(sample_patch: str) -> None:
    parsed = patch_utils.parse_unified_diff(sample_patch)
    assert len(parsed.files) == 1
    patch_file = parsed.files[0]
    assert patch_file.old_path == "test.py"
    assert patch_file.new_path == "test.py"
    assert len(patch_file.hunks) == 1
    assert patch_file.hunks[0].old_start == 1


def test_parse_multiple_files() -> None:
    patch_text = (
        "diff --git a/a.txt b/a.txt\n"
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/b.txt b/b.txt\n"
        "--- a/b.txt\n"
        "+++ b/b.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    parsed = patch_utils.parse_unified_diff(patch_text)
    assert len(parsed.files) == 2


def test_parse_new_file() -> None:
    patch_text = (
        "diff --git a/new.txt b/new.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/new.txt\n"
        "@@ -0,0 +1,2 @@\n"
        "+line1\n"
        "+line2\n"
    )
    parsed = patch_utils.parse_unified_diff(patch_text)
    patch_file = parsed.files[0]
    assert patch_file.old_path == "/dev/null"
    assert patch_file.new_path == "new.txt"


def test_parse_deleted_file() -> None:
    patch_text = (
        "diff --git a/old.txt b/old.txt\n"
        "deleted file mode 100644\n"
        "--- a/old.txt\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-line1\n"
        "-line2\n"
    )
    parsed = patch_utils.parse_unified_diff(patch_text)
    patch_file = parsed.files[0]
    assert patch_file.old_path == "old.txt"
    assert patch_file.new_path == "/dev/null"


def test_parse_multiple_hunks() -> None:
    patch_text = (
        "diff --git a/test.txt b/test.txt\n"
        "--- a/test.txt\n"
        "+++ b/test.txt\n"
        "@@ -1,2 +1,2 @@\n"
        "-line1\n"
        "+line1a\n"
        " line2\n"
        "@@ -4,2 +4,2 @@\n"
        "-line4\n"
        "+line4a\n"
        " line5\n"
    )
    parsed = patch_utils.parse_unified_diff(patch_text)
    assert len(parsed.files[0].hunks) == 2


def test_parse_invalid_format() -> None:
    patch_text = "diff --git a/test.txt b/test.txt\n--- a/test.txt\n+++ b/test.txt\n"
    with pytest.raises(patch_utils.PatchValidationError):
        patch_utils.parse_unified_diff(patch_text)


def test_parse_empty_patch() -> None:
    with pytest.raises(patch_utils.PatchValidationError):
        patch_utils.parse_unified_diff("")


def test_validate_accepts_valid_patch(sample_patch: str) -> None:
    valid, errors = patch_utils.validate_patch(
        sample_patch, Path("/repo"), patch_utils.IMMUTABLE_PATH_PATTERNS
    )
    assert valid is True
    assert errors == []


def test_validate_rejects_absolute_paths() -> None:
    patch_text = (
        "diff --git a//etc/passwd b//etc/passwd\n"
        "--- /etc/passwd\n"
        "+++ /etc/passwd\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    valid, errors = patch_utils.validate_patch(
        patch_text, Path("/repo"), patch_utils.IMMUTABLE_PATH_PATTERNS
    )
    assert valid is False
    assert any(error["type"] == "absolute_path" for error in errors)


def test_validate_rejects_outside_repo() -> None:
    patch_text = (
        "diff --git a/../secret.txt b/../secret.txt\n"
        "--- a/../secret.txt\n"
        "+++ b/../secret.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    valid, errors = patch_utils.validate_patch(
        patch_text, Path("/repo"), patch_utils.IMMUTABLE_PATH_PATTERNS
    )
    assert valid is False
    assert any(error["type"] == "outside_repo" for error in errors)


def test_validate_rejects_immutable_paths() -> None:
    patch_text = (
        "diff --git a/runs/run_001/spec_snapshot/file.txt "
        "b/runs/run_001/spec_snapshot/file.txt\n"
        "--- a/runs/run_001/spec_snapshot/file.txt\n"
        "+++ b/runs/run_001/spec_snapshot/file.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    valid, errors = patch_utils.validate_patch(
        patch_text, Path("/repo"), patch_utils.IMMUTABLE_PATH_PATTERNS
    )
    assert valid is False
    assert any(error["type"] == "immutable_path" for error in errors)


def test_validate_rejects_binary_patch() -> None:
    patch_text = (
        "diff --git a/image.png b/image.png\nBinary files a/image.png and b/image.png differ\n"
    )
    valid, errors = patch_utils.validate_patch(
        patch_text, Path("/repo"), patch_utils.IMMUTABLE_PATH_PATTERNS
    )
    assert valid is False
    assert any(error["type"] == "binary_patch" for error in errors)


def test_validate_multiple_errors() -> None:
    patch_text = (
        "diff --git a//etc/passwd b//etc/passwd\n"
        "Binary files a//etc/passwd and b//etc/passwd differ\n"
    )
    valid, errors = patch_utils.validate_patch(
        patch_text, Path("/repo"), patch_utils.IMMUTABLE_PATH_PATTERNS
    )
    assert valid is False
    types = {error["type"] for error in errors}
    assert "binary_patch" in types
    assert "absolute_path" in types


def test_git_apply_dry_run_success(sample_patch: str, fs, monkeypatch) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)

    def _fake_run(args, cwd=None):
        assert "--check" in args
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(patch_utils, "_run_git", _fake_run)
    success, error = patch_utils.apply_patch_with_git(sample_patch, repo_root, dry_run=True)
    assert success is True
    assert error == ""


def test_git_apply_dry_run_failure(sample_patch: str, fs, monkeypatch) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)

    def _fake_run(args, cwd=None):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="bad")

    monkeypatch.setattr(patch_utils, "_run_git", _fake_run)
    success, error = patch_utils.apply_patch_with_git(sample_patch, repo_root, dry_run=True)
    assert success is False
    assert "bad" in error


def test_git_apply_success(sample_patch: str, fs, monkeypatch) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)

    def _fake_run(args, cwd=None):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(patch_utils, "_run_git", _fake_run)
    success, error = patch_utils.apply_patch_with_git(sample_patch, repo_root)
    assert success is True
    assert error == ""


def test_git_apply_not_available(sample_patch: str, fs, monkeypatch) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)

    monkeypatch.setattr(patch_utils, "_run_git", lambda args, cwd=None: None)
    success, error = patch_utils.apply_patch_with_git(sample_patch, repo_root)
    assert success is False
    assert "git" in error


def test_manual_apply_simple_change(sample_patch: str, repo_with_files: Path) -> None:
    success, error = patch_utils.apply_patch_manual(sample_patch, repo_with_files)
    assert success is True
    assert error == ""
    updated = (repo_with_files / "test.py").read_text(encoding="utf-8")
    assert 'print("new")' in updated


def test_manual_apply_new_file(fs) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    patch_text = (
        "diff --git a/new.txt b/new.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/new.txt\n"
        "@@ -0,0 +1,2 @@\n"
        "+line1\n"
        "+line2\n"
    )
    success, error = patch_utils.apply_patch_manual(patch_text, repo_root)
    assert success is True
    assert error == ""
    assert (repo_root / "new.txt").read_text(encoding="utf-8") == "line1\nline2\n"


def test_manual_apply_delete_file(fs) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    (repo_root / "old.txt").write_text("line1\nline2\n", encoding="utf-8")
    patch_text = (
        "diff --git a/old.txt b/old.txt\n"
        "deleted file mode 100644\n"
        "--- a/old.txt\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-line1\n"
        "-line2\n"
    )
    success, error = patch_utils.apply_patch_manual(patch_text, repo_root)
    assert success is True
    assert error == ""
    assert not (repo_root / "old.txt").exists()


def test_manual_apply_multiple_hunks(fs) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    (repo_root / "test.txt").write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
    patch_text = (
        "diff --git a/test.txt b/test.txt\n"
        "--- a/test.txt\n"
        "+++ b/test.txt\n"
        "@@ -1,2 +1,2 @@\n"
        "-line1\n"
        "+line1a\n"
        " line2\n"
        "@@ -4,2 +4,2 @@\n"
        "-line4\n"
        "+line4a\n"
        " line5\n"
    )
    success, error = patch_utils.apply_patch_manual(patch_text, repo_root)
    assert success is True
    assert error == ""
    updated = (repo_root / "test.txt").read_text(encoding="utf-8")
    assert "line1a" in updated
    assert "line4a" in updated


def test_manual_apply_context_mismatch(fs) -> None:
    repo_root = Path("/repo")
    fs.create_dir(repo_root)
    (repo_root / "test.txt").write_text("line1\nline2\n", encoding="utf-8")
    patch_text = (
        "diff --git a/test.txt b/test.txt\n"
        "--- a/test.txt\n"
        "+++ b/test.txt\n"
        "@@ -1,2 +1,2 @@\n"
        "-lineX\n"
        "+lineY\n"
        " line2\n"
    )
    success, error = patch_utils.apply_patch_manual(patch_text, repo_root)
    assert success is False
    assert "context" in error
    updated = (repo_root / "test.txt").read_text(encoding="utf-8")
    assert updated == "line1\nline2\n"
