from scripts.servers.mcp.app.services.manager import (
    MCPBusyError,
    MCPError,
    MCPProviderCrashedError,
    MCPStdioManager,
    MCPTimeoutError,
)


class TestMCPBusyError:
    def test_default_message_and_retry(self) -> None:
        """Should have default message and retry_after_ms."""
        error = MCPBusyError()
        assert str(error) == "Provider is busy"
        assert error.retry_after_ms == 1000

    def test_custom_message_and_retry(self) -> None:
        """Should accept custom message and retry_after_ms."""
        error = MCPBusyError("Custom busy", retry_after_ms=5000)
        assert str(error) == "Custom busy"
        assert error.retry_after_ms == 5000


class TestMCPProviderCrashedError:
    def test_default_message(self) -> None:
        """Should have default crash message."""
        error = MCPProviderCrashedError()
        assert "crashed and was restarted" in str(error)

    def test_custom_message(self) -> None:
        """Should accept custom message."""
        error = MCPProviderCrashedError("Custom crash message")
        assert str(error) == "Custom crash message"
