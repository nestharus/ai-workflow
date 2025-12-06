"""Shared fixtures for script tests using pyfakefs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


# --- Patch thinc's fix_random_seed to handle seeds >= 2**32 ---
# pytest-randomly may pass seeds that exceed numpy's 32-bit limit.
# thinc registers a pytest_randomly.random_seeder entry point that calls
# numpy.random.seed() directly without constraining the seed value.
# This patch applies modulo 2**32 to prevent ValueError.
try:
    import thinc.util as _thinc_util  # type: ignore[import-not-found]

    _original_fix_random_seed = _thinc_util.fix_random_seed

    def _patched_fix_random_seed(seed: int = 0) -> None:
        """Wrapper that constrains seed to 32-bit range for numpy compatibility."""
        _original_fix_random_seed(seed % (2**32))

    _thinc_util.fix_random_seed = _patched_fix_random_seed
except ImportError:
    pass  # thinc not installed, no patch needed


@pytest.fixture
def fake_repo_root(fs: FakeFilesystem) -> Path:
    """Create a fake repository root with standard structure.

    The fake filesystem is automatically provided by pyfakefs's `fs` fixture.
    This fixture sets up a minimal repo structure for testing scripts.
    """
    repo_root = Path("/fake/repo")
    fs.create_dir(str(repo_root))
    fs.create_dir(str(repo_root / "app"))
    fs.create_dir(str(repo_root / "scripts"))
    fs.create_dir(str(repo_root / "tests"))
    fs.create_dir(str(repo_root / "tools"))
    fs.create_dir(str(repo_root / "docs"))
    fs.create_dir(str(repo_root / ".knowledge"))
    fs.create_dir(str(repo_root / ".review"))
    return repo_root


@pytest.fixture
def real_knowledge_path(tmp_path: Path) -> Path:
    """Create a real .knowledge directory for DuckDB tests.

    DuckDB reads from the real filesystem, so pyfakefs cannot be used.
    This fixture provides real temp directories for DuckDB testing.
    """
    knowledge = tmp_path / ".knowledge"
    (knowledge / "comparisons").mkdir(parents=True)
    (knowledge / "resolutions").mkdir(parents=True)
    (knowledge / "migrations").mkdir(parents=True)
    (knowledge / "originals").mkdir(parents=True)
    (knowledge / "additions").mkdir(parents=True)
    (knowledge / "movements").mkdir(parents=True)
    (knowledge / "reports").mkdir(parents=True)
    return knowledge


@pytest.fixture
def knowledge_path(fake_repo_root: Path, fs: FakeFilesystem) -> Path:
    """Create a .knowledge directory structure for testing."""
    knowledge = fake_repo_root / ".knowledge"
    fs.create_dir(str(knowledge / "comparisons"))
    fs.create_dir(str(knowledge / "resolutions"))
    fs.create_dir(str(knowledge / "migrations"))
    fs.create_dir(str(knowledge / "originals"))
    fs.create_dir(str(knowledge / "additions"))
    fs.create_dir(str(knowledge / "movements"))
    fs.create_dir(str(knowledge / "reports"))
    return knowledge


@pytest.fixture
def sample_yaml_content() -> str:
    """Return sample YAML content for testing."""
    return """doc_id: test.api-patterns
scope: Test API patterns
sections:
  - id: section-1
    title: Test Section
    items:
      - id: item-1
        text: First test item description
      - id: item-2
        text: Second test item description
        description: Additional description
"""


@pytest.fixture
def sample_yaml_file(fake_repo_root: Path, fs: FakeFilesystem, sample_yaml_content: str) -> Path:
    """Create a sample YAML file for testing."""
    yaml_path = fake_repo_root / "docs" / "test.yml"
    fs.create_file(str(yaml_path), contents=sample_yaml_content)
    return yaml_path


@pytest.fixture
def sample_csv_content() -> str:
    """Return sample CSV content for comparison testing."""
    return """source_file,id,origin_type,original_text,split_file,split_text
docs/original.api-patterns.yml,item-1,original,First item text,docs/python/\
python.api-patterns.yml,First item text modified
docs/original.api-patterns.yml,item-2,original,Second item text,docs/python/\
python.api-patterns.yml,Second item text
docs/python/python.api-patterns.yml,item-3,split_only,New item text,,
"""


@pytest.fixture
def comparison_csv_file(knowledge_path: Path, fs: FakeFilesystem, sample_csv_content: str) -> Path:
    """Create a sample comparison CSV file for testing."""
    csv_path = knowledge_path / "comparisons" / "api-patterns.csv"
    fs.create_file(str(csv_path), contents=sample_csv_content)
    return csv_path
