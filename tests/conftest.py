"""
Test Fixtures Module.

This module implements the Composition Root pattern for the test suite, providing
centralized fixture definitions for both integration and end-to-end (E2E) tests.

It supports two distinct testing tiers:
1. Integration Tests (Fast):
   - Run in-process using `httpx.ASGITransport`.
   - Use `async_client` fixture.
   - Mock external dependencies but execute full application code.
   - No network overhead.

2. E2E Tests (Slow):
   - Run against a live server process using `subprocess`.
   - Use `api_client` fixture.
   - Verify the full stack including startup scripts, health checks, and networking.
   - Marked with `@pytest.mark.e2e`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.factory import create_app
from app.core.settings import Settings

logger = logging.getLogger(__name__)


class DockerBuildError(RuntimeError):
    """Raised when the Docker image build fails during E2E setup."""

    def __init__(self, stderr: str) -> None:
        """Attach stderr output from the failed build."""
        super().__init__(f"Docker image build failed: {stderr}")


class DockerStartupTimeoutError(RuntimeError):
    """Raised when the containerized server does not become healthy in time."""

    def __init__(self, container_name: str, timeout: float) -> None:
        """Report the timeout and container name involved."""
        message = (
            f"Dockerized server failed to start within {timeout} seconds; "
            f"see docker logs for {container_name}"
        )
        super().__init__(message)


class DockerExecutableNotFoundError(FileNotFoundError):
    """Raised when the docker CLI is missing from PATH."""

    def __init__(self) -> None:
        super().__init__("Docker executable not found on PATH")


# --- Integration Test Fixtures (In-Process) ---


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
        surrealdb_pass="TestPass12!Xyz$",  # noqa: S106
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


# --- E2E Test Fixtures (Dockerized Live Server) ---


def _resolve_test_port() -> int:
    """Return test port from env or allocate an ephemeral free port."""
    env_port = os.getenv("TEST_PORT")
    try:
        if env_port and env_port != "0":
            return int(env_port)
    except ValueError:
        logger.warning("Invalid TEST_PORT '%s'; falling back to ephemeral port", env_port)

    # NOTE: Race condition exists here. The port is freed when the socket closes,
    # allowing another process to claim it before Docker binds. Mitigations include:
    # - Keeping the socket open until the service binds (not always feasible)
    # - Letting Docker pick and reading the mapped port afterward
    # - Retrying on bind failure with a new ephemeral port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        _, port = sock.getsockname()

    os.environ["TEST_PORT"] = str(port)
    return port


TEST_PORT = _resolve_test_port()
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


def _docker_exe() -> str:
    docker_path = shutil.which("docker")
    if docker_path is None:
        raise DockerExecutableNotFoundError()
    return docker_path


def _docker_run(
    args: list[str], *, check: bool = False, **kwargs: object
) -> subprocess.CompletedProcess:
    command = [_docker_exe(), *args]
    return subprocess.run(command, check=check, **kwargs)  # noqa: S603


@pytest.fixture(scope="session")
def live_server() -> Iterator[str]:
    """
    Launch a dockerized live server for E2E tests.

    Uses docker-compose to launch the full stack so dependencies (DB, search)
    match production composition.
    """
    compose_env = {**os.environ, "TEST_PORT": str(TEST_PORT)}
    stack_name = "docker-compose stack"

    # Run docker-compose to build and start the api stack with dependencies
    try:
        _docker_run(
            ["compose", "-f", "docker-compose.yml", "up", "-d", "--build", "api"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=compose_env,
        )
    except subprocess.CalledProcessError as exc:
        stderr_output = exc.stderr.decode("utf-8") if exc.stderr else ""
        raise DockerBuildError(stderr_output) from exc
    # Poll for health
    # Elasticsearch has a 60s start_period + 30s healthcheck interval,
    # so we need more time for the full stack to become healthy
    start_time = time.time()
    timeout = 120.0  # seconds
    healthy = False

    with httpx.Client() as client:
        while time.time() - start_time < timeout:
            try:
                response = client.get(f"{BASE_URL}/health")
                try:
                    payload = response.json()
                except (json.JSONDecodeError, ValueError):
                    time.sleep(0.5)
                    continue
                if response.status_code == 200 and payload.get("status") == "ok":
                    healthy = True
                    break
            except httpx.RequestError:
                pass
            time.sleep(0.5)

    if not healthy:
        logs_result = _docker_run(
            ["compose", "-f", "docker-compose.yml", "logs"],
            capture_output=True,
            text=True,
            env=compose_env,
        )
        log_output = logs_result.stdout.strip() if logs_result.stdout else ""
        if log_output:
            logger.error("compose logs while failing health check:\n%s", log_output)
        else:
            logger.error("compose did not produce startup logs")

        _docker_run(
            ["compose", "-f", "docker-compose.yml", "down", "--remove-orphans"],
            capture_output=True,
            env=compose_env,
        )
        raise DockerStartupTimeoutError(stack_name, timeout)

    try:
        yield BASE_URL
    finally:
        # 5. Teardown
        _docker_run(
            [
                "compose",
                "-f",
                "docker-compose.yml",
                "down",
                "--remove-orphans",
                "--volumes",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=compose_env,
        )


@pytest_asyncio.fixture
async def api_client(live_server: str) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an async client configured for the live server (E2E tests)."""
    async with httpx.AsyncClient(base_url=live_server, timeout=5.0) as ac:
        yield ac


# --- Use-Case Coverage Reporting Hooks ---


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the use-case coverage threshold configuration options."""
    parser.addini(
        "usecase_coverage_threshold_e2e",
        "Minimum e2e use-case coverage percentage required (0-100)",
        default="100",
    )
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
        "by_tier": {"e2e": [], "integration": []},
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
    by_tier: dict[str, list[str]] = {"e2e": [], "integration": []}

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

    # Parse e2e threshold with error handling
    e2e_threshold_str = config.getini("usecase_coverage_threshold_e2e")
    e2e_threshold = 100.0
    if e2e_threshold_str:
        try:
            e2e_threshold = float(e2e_threshold_str)
            if e2e_threshold < 0 or e2e_threshold > 100:
                logger.warning(
                    "usecase_coverage_threshold_e2e value %.1f is outside valid range (0-100), "
                    "clamping to valid range",
                    e2e_threshold,
                )
                e2e_threshold = max(0.0, min(100.0, e2e_threshold))
        except ValueError:
            logger.warning(
                "Invalid usecase_coverage_threshold_e2e value '%s', using default of 100.0",
                e2e_threshold_str,
            )
            e2e_threshold = 100.0

    e2e_stats = tier_stats.get("e2e", {"percentage": 100.0})
    if e2e_stats["percentage"] < e2e_threshold:
        threshold_failures.append(
            f"e2e coverage {e2e_stats['percentage']:.1f}% < {e2e_threshold:.1f}%"
        )

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
