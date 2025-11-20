import pytest
import pytest_check as check
from httpx import AsyncClient

# Mark all tests in this file as 'e2e' and 'asyncio'
pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


async def test_health_check_e2e(api_client: AsyncClient) -> None:
    """
    Tests the health check endpoint on the live server.
    """
    # Arrange: 'api_client' comes from tests/conftest.py
    url = "/health"

    # Act: This is a REAL HTTP request
    response = await api_client.get(url)

    # Assert
    check.equal(response.status_code, 200, "Health check should return 200")
    check.equal(response.json().get("status"), "ok", "Health check status should be 'ok'")
