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

import logging
import os
import shutil
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
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

    Note: This currently uses default values as the Settings model is simple.
    In the future, if testing-specific overrides (like debug flags or mocked paths)
    are added to Settings, they should be explicitly configured here to ensure
    reproducible test environments.
    """
    return Settings()


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
    _docker_run(
        ["compose", "-f", "docker-compose.yml", "up", "-d", "--build", "api"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=compose_env,
    )
    # 4. Poll for health
    start_time = time.time()
    timeout = 20.0  # seconds
    healthy = False

    with httpx.Client() as client:
        while time.time() - start_time < timeout:
            try:
                response = client.get(f"{BASE_URL}/health")
                if response.status_code == 200 and response.json().get("status") == "ok":
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
