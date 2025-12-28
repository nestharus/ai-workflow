from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts.dev.linter.base import is_path_excluded

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


@pytest.fixture
def fake_repo(fs: FakeFilesystem) -> Path:
    """Create a fake repository root for testing."""
    repo_root = Path("/fake/repo")
    fs.create_dir(str(repo_root))
    return repo_root


class TestIsPathExcluded:
    def test_path_in_excluded_directory(self) -> None:
        """Should return True when path is under an excluded directory."""
        exclude_paths = {Path("/repo/.tmp"), Path("/repo/.worktrees")}
        path = Path("/repo/.tmp/test.yaml")
        assert is_path_excluded(path, exclude_paths) is True

    def test_path_not_in_excluded_directory(self) -> None:
        """Should return False when path is not under an excluded directory."""
        exclude_paths = {Path("/repo/.tmp"), Path("/repo/.worktrees")}
        path = Path("/repo/config.yaml")
        assert is_path_excluded(path, exclude_paths) is False

    def test_nested_excluded_path(self) -> None:
        """Should return True when path is deeply nested under excluded directory."""
        exclude_paths = {Path("/repo/.tmp")}
        path = Path("/repo/.tmp/deep/nested/file.yaml")
        assert is_path_excluded(path, exclude_paths) is True

    def test_path_equals_excluded_directory(self) -> None:
        """Should return True when path exactly equals an excluded directory."""
        exclude_paths = {Path("/repo/.tmp")}
        path = Path("/repo/.tmp")
        assert is_path_excluded(path, exclude_paths) is True


class TestRunDetectSecrets:
    @pytest.fixture
    def detect_secrets_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create detect-secrets configuration and baseline files."""
        config = fake_repo / ".lint.detect-secrets.yaml"
        fs.create_file(
            str(config),
            contents=(
                "excluded_extensions:\n"
                "  - .pyc\n"
                "  - .png\n"
                "  - .jpg\n"
                "  - .db\n"
                "  - .sqlite\n"
                "  - .zip\n"
                "  - .tar\n"
                "  - .gz\n"
                "excluded_names:\n"
                "  - uv.lock\n"
                "  - .secrets.baseline\n"
            ),
        )
        baseline = fake_repo / ".secrets.baseline"
        fs.create_file(str(baseline), contents='{"version": "1.0.0"}')
        return config


class TestRunGitleaks:
    @pytest.fixture
    def gitleaks_config(self, fake_repo: Path, fs: FakeFilesystem) -> Path:
        """Create gitleaks configuration files."""
        lint_config = fake_repo / ".lint.gitleaks.yaml"
        # Use included_paths format to match actual config structure
        fs.create_file(
            str(lint_config),
            contents=(
                "excluded_extensions:\n"
                "  - .pyc\n"
                "  - .png\n"
                "  - .jpg\n"
                "  - .db\n"
                "  - .sqlite\n"
                "  - .zip\n"
                "  - .tar\n"
                "  - .gz\n"
                "excluded_names:\n"
                "  - uv.lock\n"
                "  - .secrets.baseline\n"
                "included_paths:\n"
                "  - '*'\n"
                "  - 'app/**'\n"
                "  - 'scripts/**'\n"
                "  - 'tests/**'\n"
            ),
        )
        gitleaks_toml = fake_repo / ".gitleaks.toml"
        fs.create_file(str(gitleaks_toml), contents="[[ rules ]]")
        return gitleaks_toml


class TestSecretScannerConsistency:
    @pytest.fixture
    def gitleaks_config(self) -> dict:
        """Load the real gitleaks config from the project root."""
        import yaml

        config_path = (
            Path(__file__).resolve().parent.parent.parent.parent.parent / ".lint.gitleaks.yaml"
        )
        if not config_path.exists():
            pytest.skip(f"Gitleaks config not found at {config_path}")
        with config_path.open() as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def detect_secrets_config(self) -> dict:
        """Load the real detect-secrets config from the project root."""
        import yaml

        config_path = (
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / ".lint.detect-secrets.yaml"
        )
        if not config_path.exists():
            pytest.skip(f"Detect-secrets config not found at {config_path}")
        with config_path.open() as f:
            return yaml.safe_load(f)

    def test_excluded_extensions_match(
        self, gitleaks_config: dict, detect_secrets_config: dict
    ) -> None:
        """Gitleaks excluded_extensions must match detect-secrets excluded_extensions."""
        gitleaks_exts = set(gitleaks_config.get("excluded_extensions", []))
        detect_secrets_exts = set(detect_secrets_config.get("excluded_extensions", []))
        assert gitleaks_exts == detect_secrets_exts, (
            f"Extension mismatch: gitleaks has {gitleaks_exts - detect_secrets_exts}, "
            f"detect-secrets has {detect_secrets_exts - gitleaks_exts}"
        )

    def test_excluded_names_match(self, gitleaks_config: dict, detect_secrets_config: dict) -> None:
        """Gitleaks excluded_names must match detect-secrets excluded_names."""
        gitleaks_names = set(gitleaks_config.get("excluded_names", []))
        detect_secrets_names = set(detect_secrets_config.get("excluded_names", []))
        assert gitleaks_names == detect_secrets_names, (
            f"Name mismatch: gitleaks has {gitleaks_names - detect_secrets_names}, "
            f"detect-secrets has {detect_secrets_names - gitleaks_names}"
        )

    def test_included_paths_does_not_include_canonical_excluded_dirs(
        self, gitleaks_config: dict
    ) -> None:
        """Gitleaks included_paths must not include directories that should be excluded."""
        # Canonical directories that should NOT be included per pre-commit detect-secrets exclude.
        # MAINTAINER NOTE: Keep this set in sync with the detect-secrets hook's
        # exclude regex in .pre-commit-config.yaml. If that config changes,
        # update this set accordingly.
        excluded_dirs = {
            ".venv",
            "node_modules",
            "htmlcov",
            ".coverage",
            "openapi",
            ".review",
            ".tmp",
            ".worktrees",
            ".tasks/store",
            ".huggingface",
            ".serena",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".git-rewrite",
            "to_adapt",
            ".idea",
            "build",
            "dist",
        }
        included_paths = gitleaks_config.get("included_paths", [])
        # Check that none of the excluded directories are explicitly included
        for path in included_paths:
            # Skip negation patterns (these are exclusions which is correct)
            if path.startswith("!"):
                continue
            for excluded_dir in excluded_dirs:
                # Check if the pattern would include files from excluded directories
                if path.startswith(f"{excluded_dir}/") or path.startswith(f"{excluded_dir}/**"):
                    raise AssertionError(
                        f"Gitleaks included_paths contains pattern '{path}' "
                        f"which includes excluded directory '{excluded_dir}'"
                    )
