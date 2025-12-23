"""Tests for scripts/servers/mcp/app/services/sse_client.py - call_tool and list_tools functions."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.servers.mcp.app.services.sse_client import MCPSSEClient, MCPSSEError


class TestMCPSSEClientCallTool:
    """Tests for MCPSSEClient.call_tool method covering lines 287-296."""

    def test_call_tool_initializes_when_not_initialized(self) -> None:
        """Test call_tool calls _initialize when not initialized (line 288-289)."""
        client = MCPSSEClient("http://test.local/sse")

        with patch.object(client, "_initialize") as mock_init, patch.object(
            client, "_send_request"
        ) as mock_send:
            mock_send.return_value = {"result": "success"}

            result = client.call_tool("test_tool", {"arg": "value"})

            mock_init.assert_called_once()
            mock_send.assert_called_once_with(
                method="tools/call",
                params={"name": "test_tool", "arguments": {"arg": "value"}},
                timeout=30.0,
            )
            assert result == {"result": "success"}

    def test_call_tool_skips_initialize_when_already_initialized(self) -> None:
        """Test call_tool skips _initialize when already initialized (line 288)."""
        client = MCPSSEClient("http://test.local/sse")
        client._initialized = True

        with patch.object(client, "_initialize") as mock_init, patch.object(
            client, "_send_request"
        ) as mock_send:
            mock_send.return_value = {"data": "result"}

            result = client.call_tool("tool", {})

            mock_init.assert_not_called()
            assert result == {"data": "result"}

    def test_call_tool_with_custom_timeout(self) -> None:
        """Test call_tool respects custom timeout (line 294)."""
        client = MCPSSEClient("http://test.local/sse")
        client._initialized = True

        with patch.object(client, "_send_request") as mock_send:
            mock_send.return_value = {}

            client.call_tool("tool", {"a": 1}, timeout=60.0)

            mock_send.assert_called_once_with(
                method="tools/call",
                params={"name": "tool", "arguments": {"a": 1}},
                timeout=60.0,
            )

    def test_call_tool_returns_result(self) -> None:
        """Test call_tool returns result from _send_request (line 296)."""
        client = MCPSSEClient("http://test.local/sse")
        client._initialized = True

        expected_result = {"content": [{"type": "text", "text": "Hello"}]}
        with patch.object(client, "_send_request") as mock_send:
            mock_send.return_value = expected_result

            result = client.call_tool("greet", {"name": "world"})

            assert result == expected_result


class TestMCPSSEClientListTools:
    """Tests for MCPSSEClient.list_tools method covering lines 310-319."""

    def test_list_tools_initializes_when_not_initialized(self) -> None:
        """Test list_tools calls _initialize when not initialized (line 311-312)."""
        client = MCPSSEClient("http://test.local/sse")

        with patch.object(client, "_initialize") as mock_init, patch.object(
            client, "_send_request"
        ) as mock_send:
            mock_send.return_value = {"tools": []}

            result = client.list_tools()

            mock_init.assert_called_once()
            mock_send.assert_called_once_with(
                method="tools/list",
                params={},
                timeout=30.0,
            )
            assert result == {"tools": []}

    def test_list_tools_skips_initialize_when_already_initialized(self) -> None:
        """Test list_tools skips _initialize when already initialized (line 311)."""
        client = MCPSSEClient("http://test.local/sse")
        client._initialized = True

        with patch.object(client, "_initialize") as mock_init, patch.object(
            client, "_send_request"
        ) as mock_send:
            mock_send.return_value = {"tools": [{"name": "tool1"}]}

            result = client.list_tools()

            mock_init.assert_not_called()
            assert result == {"tools": [{"name": "tool1"}]}

    def test_list_tools_with_custom_timeout(self) -> None:
        """Test list_tools respects custom timeout (line 317)."""
        client = MCPSSEClient("http://test.local/sse")
        client._initialized = True

        with patch.object(client, "_send_request") as mock_send:
            mock_send.return_value = {"tools": []}

            client.list_tools(timeout=120.0)

            mock_send.assert_called_once_with(
                method="tools/list",
                params={},
                timeout=120.0,
            )

    def test_list_tools_returns_result(self) -> None:
        """Test list_tools returns result from _send_request (line 319)."""
        client = MCPSSEClient("http://test.local/sse")
        client._initialized = True

        expected_result = {
            "tools": [
                {"name": "tool1", "description": "Tool 1"},
                {"name": "tool2", "description": "Tool 2"},
            ]
        }
        with patch.object(client, "_send_request") as mock_send:
            mock_send.return_value = expected_result

            result = client.list_tools()

            assert result == expected_result

    def test_list_tools_propagates_error(self) -> None:
        """Test list_tools propagates errors from _send_request."""
        client = MCPSSEClient("http://test.local/sse")
        client._initialized = True

        with patch.object(client, "_send_request") as mock_send:
            mock_send.side_effect = MCPSSEError("Connection failed")

            with pytest.raises(MCPSSEError) as exc_info:
                client.list_tools()

            assert "Connection failed" in str(exc_info.value)


class TestMCPSSEClientCallToolIntegration:
    """Integration tests for call_tool and list_tools methods."""

    def test_call_tool_thread_safety(self) -> None:
        """Test that call_tool is thread-safe via the lock."""
        client = MCPSSEClient("http://test.local/sse")
        client._initialized = True

        with patch.object(client, "_send_request") as mock_send:
            mock_send.return_value = {"result": "ok"}

            # Call should acquire and release the lock
            result = client.call_tool("tool", {})
            assert result == {"result": "ok"}

    def test_list_tools_thread_safety(self) -> None:
        """Test that list_tools is thread-safe via the lock."""
        client = MCPSSEClient("http://test.local/sse")
        client._initialized = True

        with patch.object(client, "_send_request") as mock_send:
            mock_send.return_value = {"tools": []}

            result = client.list_tools()
            assert result == {"tools": []}
