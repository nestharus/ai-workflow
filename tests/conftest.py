"""
Test Fixtures Module.

This module implements the Composition Root pattern for the test suite, providing
centralized fixture definitions for integration tests.

Integration Tests (Fast):
- Run in-process using `httpx.ASGITransport`.
- Use `async_client` fixture.
- Mock external dependencies but execute full application code.
- No network overhead.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

_SPEC_MANAGER_ROOT = (Path(__file__).resolve().parents[1] / "scripts" / "spec_manager").resolve()
if _SPEC_MANAGER_ROOT.exists() and str(_SPEC_MANAGER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPEC_MANAGER_ROOT))

import httpx
import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from spec_manager.refinement.workspace import Phase, WorkspaceManager

from app.core.factory import create_app
from app.core.settings import Settings
from tests.spec_refinement.fixtures.agent_mocks import MockAgentController
from tests.spec_refinement.fixtures.test_corpus import create_test_corpus
from tests.spec_refinement.test_performance import PerformanceBenchmark

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

logger = logging.getLogger(__name__)

# --- Test Fixtures ---


@pytest.fixture
def test_settings() -> Settings:
    """
    Provide a Settings instance for testing.

    Explicitly provides test-safe credentials so tests do not depend on external
    environment variables. In the future, if testing-specific overrides (like debug
    flags or mocked paths) are added to Settings, they should be explicitly
    configured here to ensure reproducible test environments.
    """
    # Test-only credentials that satisfy complexity requirements; never used in production
    return Settings(
        surrealdb_user="TestUser12!Abc#",
        surrealdb_pass="TestPass12!Xyz$",
    )


@pytest.fixture
def test_app(test_settings: Settings) -> FastAPI:
    """Create a FastAPI application instance for testing."""
    return create_app(test_settings)


@pytest.fixture
def client(test_app: FastAPI) -> Iterator[TestClient]:
    """Yield a synchronous TestClient for basic route testing."""
    with TestClient(test_app) as c:
        yield c


@pytest.fixture
def client_include_error_body(test_settings: Settings) -> Iterator[TestClient]:
    """Yield a TestClient with include_error_body enabled for validation testing."""
    # We update the model copy to ensure isolation
    settings = test_settings.model_copy(update={"include_error_body": True})
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture
async def async_client(test_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an async client for integration tests (in-process)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac


# --- Use-Case Coverage Reporting Hooks ---


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the use-case coverage threshold configuration options."""
    parser.addini(
        "usecase_coverage_threshold_integration",
        "Minimum integration use-case coverage percentage required (0-100)",
        default="100",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with test credentials and use-case registry.

    Sets default test credentials for SurrealDB before any modules are imported,
    ensuring Settings validation succeeds during test collection. Uses setdefault
    so explicit env vars (e.g., for integration tests) take precedence.
    """
    # Set test-safe credentials before any Settings instantiation
    os.environ.setdefault("SURREALDB_USER", "TestUser12!Abc#")
    os.environ.setdefault("SURREALDB_PASS", "TestPass12!Xyz$")

    # Load use-case registry for coverage tracking
    registry_path = Path(__file__).parent / "docs" / "use_cases.yaml"

    usecase_registry: dict = {
        "all_ids": [],
        "by_feature": {},
        "by_tier": {"integration": []},
        "metadata": {"version": "unknown", "last_updated": "unknown"},
    }

    if not registry_path.exists():
        logger.warning("Use-case registry not found at %s", registry_path)
        config._usecase_registry = usecase_registry  # type: ignore[attr-defined]
        return

    try:
        with registry_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.warning("Failed to parse use-case registry YAML: %s", e)
        config._usecase_registry = usecase_registry  # type: ignore[attr-defined]
        return

    if not data:
        logger.warning("Use-case registry is empty")
        config._usecase_registry = usecase_registry  # type: ignore[attr-defined]
        return

    # Extract metadata
    usecase_registry["metadata"] = {
        "version": data.get("version", "unknown"),
        "last_updated": data.get("last_updated", "unknown"),
    }

    # Extract use-case IDs from features
    features = data.get("features", {})
    all_ids: list[str] = []
    by_feature: dict[str, list[str]] = {}
    by_tier: dict[str, list[str]] = {"integration": []}

    for feature_key, feature_data in features.items():
        feature_name = feature_data.get("name", feature_key)
        use_cases = feature_data.get("use_cases", [])
        feature_ids: list[str] = []

        for use_case in use_cases:
            uc_id = use_case.get("id")
            if uc_id:
                all_ids.append(uc_id)
                feature_ids.append(uc_id)
                # Track by tier
                tier = use_case.get("test_tier", "integration")
                if tier in by_tier:
                    by_tier[tier].append(uc_id)

        if feature_ids:
            by_feature[feature_name] = feature_ids

    usecase_registry["all_ids"] = all_ids
    usecase_registry["by_feature"] = by_feature
    usecase_registry["by_tier"] = by_tier

    config._usecase_registry = usecase_registry  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Generate use-case coverage report after test session completes."""
    config = session.config
    registry: dict = getattr(config, "_usecase_registry", None)  # type: ignore[attr-defined]

    if not registry or not registry.get("all_ids"):
        return

    has_integration_tests = any(
        "/tests/integration/" in str(item.fspath).replace("\\", "/") for item in session.items
    )
    if not has_integration_tests:
        return

    all_ids: list[str] = registry["all_ids"]
    by_feature: dict[str, list[str]] = registry["by_feature"]
    by_tier: dict[str, list[str]] = registry["by_tier"]

    # Collect covered use-case IDs from test markers
    covered_ids: set[str] = set()
    for item in session.items:
        for marker in item.iter_markers("usecase"):
            if marker.args:
                covered_ids.add(marker.args[0])

    # Calculate overall coverage statistics
    total_count = len(all_ids)
    covered_count = len(covered_ids & set(all_ids))
    uncovered_count = total_count - covered_count
    coverage_pct = (covered_count / total_count * 100) if total_count > 0 else 100.0

    # Calculate per-tier coverage
    tier_stats: dict[str, dict] = {}
    for tier_name, tier_ids in by_tier.items():
        tier_total = len(tier_ids)
        tier_covered = len(covered_ids & set(tier_ids))
        tier_uncovered = tier_total - tier_covered
        tier_pct = (tier_covered / tier_total * 100) if tier_total > 0 else 100.0
        uncovered_list = [uc_id for uc_id in tier_ids if uc_id not in covered_ids]
        tier_stats[tier_name] = {
            "total": tier_total,
            "covered": tier_covered,
            "uncovered": tier_uncovered,
            "percentage": tier_pct,
            "uncovered_ids": uncovered_list,
        }

    # Build uncovered IDs by feature
    uncovered_by_feature: dict[str, list[str]] = {}
    for feature_name, feature_ids in by_feature.items():
        uncovered = [uc_id for uc_id in feature_ids if uc_id not in covered_ids]
        if uncovered:
            uncovered_by_feature[feature_name] = uncovered

    # Get terminal reporter for output
    terminalreporter = config.pluginmanager.get_plugin("terminalreporter")

    def write_line(msg: str) -> None:
        if terminalreporter:
            terminalreporter.write_line(msg)
        else:
            print(msg)

    # Print coverage report
    write_line("")
    write_line("=" * 70)
    write_line("USE-CASE COVERAGE REPORT")
    write_line("=" * 70)
    write_line(f"Registry Version: {registry['metadata']['version']}")
    write_line(f"Last Updated: {registry['metadata']['last_updated']}")
    write_line("-" * 70)
    write_line(f"Total Use-Cases:     {total_count:>4}")
    write_line(f"Covered:             {covered_count:>4}")
    write_line(f"Uncovered:           {uncovered_count:>4}")
    write_line(f"Coverage:            {coverage_pct:>6.1f}%")
    write_line("-" * 70)

    # Coverage by tier
    write_line("COVERAGE BY TIER:")
    for tier_name, stats in tier_stats.items():
        write_line(
            f"  {tier_name}: {stats['covered']}/{stats['total']} ({stats['percentage']:.1f}%)"
        )

    write_line("-" * 70)

    # Breakdown by feature
    write_line("COVERAGE BY FEATURE:")
    for feature_name, feature_ids in by_feature.items():
        feature_covered = len([uc_id for uc_id in feature_ids if uc_id in covered_ids])
        feature_total = len(feature_ids)
        feature_pct = (feature_covered / feature_total * 100) if feature_total > 0 else 100.0
        write_line(f"  {feature_name}: {feature_covered}/{feature_total} ({feature_pct:.1f}%)")

    # Detailed uncovered list by tier
    write_line("-" * 70)
    write_line("UNCOVERED USE-CASES BY TIER:")
    for tier_name, stats in tier_stats.items():
        if stats["uncovered_ids"]:
            write_line(f"  {tier_name}:")
            for uc_id in stats["uncovered_ids"]:
                write_line(f"    - {uc_id}")

    write_line("=" * 70)

    # Check per-tier thresholds and collect failures
    threshold_failures: list[str] = []

    # Parse integration threshold with error handling
    integration_threshold_str = config.getini("usecase_coverage_threshold_integration")
    integration_threshold = 100.0
    if integration_threshold_str:
        try:
            integration_threshold = float(integration_threshold_str)
            if integration_threshold < 0 or integration_threshold > 100:
                logger.warning(
                    "usecase_coverage_threshold_integration value %.1f is outside valid range "
                    "(0-100), clamping to valid range",
                    integration_threshold,
                )
                integration_threshold = max(0.0, min(100.0, integration_threshold))
        except ValueError:
            logger.warning(
                "Invalid usecase_coverage_threshold_integration value '%s', using default of 100.0",
                integration_threshold_str,
            )
            integration_threshold = 100.0

    integration_stats = tier_stats.get("integration", {"percentage": 100.0})
    if integration_stats["percentage"] < integration_threshold:
        threshold_failures.append(
            f"integration coverage {integration_stats['percentage']:.1f}% "
            f"< {integration_threshold:.1f}%"
        )

    if threshold_failures:
        write_line("")
        write_line("ERROR: Use-case coverage thresholds not met:")
        for failure in threshold_failures:
            write_line(f"  - {failure}")
        session.exitstatus = 1


# --- Spec Refinement Integration Fixtures ---


@pytest.fixture
def spec_refinement_workspace(fs, monkeypatch):
    def _factory(*, run_id: str = "run_001", file_count: int | None = None):
        base = Path("/work")
        fs.create_dir(base)
        input_dir = base / "specs"
        manifest = create_test_corpus(fs, input_dir, file_count=file_count)
        monkeypatch.chdir(base)
        manager = WorkspaceManager(run_id=run_id, input_folder=input_dir)
        issues = manager.initialize(force=True)
        assert issues == []
        manager.start_phase(Phase.SECTIONIZATION)
        manager.complete_phase(Phase.SECTIONIZATION, outputs={"files_processed": 0})
        return manager, manifest

    return _factory


@pytest.fixture
def mock_all_agents(monkeypatch):
    def _apply(
        manifest: dict[str, dict[str, object]],
        *,
        violation_rate: float = 0.15,
        spec_patch_violation: str = "invalid_citation",
        mapping_violation_mode: str = "invalid_citation",
        gap_mode: str = "empty",
        overrides: dict[str, float] | None = None,
    ) -> MockAgentController:
        controller = MockAgentController(
            manifest=manifest,
            violation_rate=violation_rate,
            spec_patch_violation=spec_patch_violation,
            mapping_violation_mode=mapping_violation_mode,
            gap_mode=gap_mode,
        )
        if overrides:
            controller.violation_overrides.update(overrides)

        monkeypatch.setattr(
            "scripts.spec_refinement.workflows.summarization.run_agent",
            controller.dispatch,
        )
        monkeypatch.setattr(
            "scripts.spec_refinement.workflows.library_labeling.run_agent",
            controller.dispatch,
        )
        monkeypatch.setattr(
            "scripts.spec_refinement.workflows.evidence_expansion.run_agent",
            controller.dispatch,
        )
        monkeypatch.setattr(
            "scripts.spec_refinement.workflows.spec_building.run_agent",
            controller.dispatch,
        )
        monkeypatch.setattr(
            "scripts.spec_refinement.workflows.sublibrary_detection.run_agent",
            controller.dispatch,
        )
        monkeypatch.setattr(
            "scripts.spec_refinement.workflows.architecture.run_agent",
            controller.dispatch,
        )
        monkeypatch.setattr(
            "spec_manager.refinement.repair.run_agent",
            controller.dispatch,
        )

        return controller

    return _apply


@pytest.fixture
def performance_tracker() -> PerformanceBenchmark:
    return PerformanceBenchmark()
