"""Tests for MCP bridge protocol serialization."""

from __future__ import annotations

import json

import pytest

from scripts.servers.mcp.protocol import (
    CallToolRequest,
    ErrorDetail,
    ErrorEnvelope,
    ErrorType,
    GetServerToolRequest,
    HealthRequest,
    HealthResponse,
    ListServersRequest,
    ListToolsRequest,
    MCPCallResponse,
    ServerInfo,
    ServersResponse,
    SuccessEnvelope,
    create_error_response,
    create_success_response,
    parse_request,
    parse_response,
    to_json,
)


class TestListServersRequest:
    """Tests for ListServersRequest."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        request = ListServersRequest(id="test-id")

        json_str = request.to_json()
        data = json.loads(json_str)

        assert data["method"] == "list_servers"
        assert data["id"] == "test-id"

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "method": "list_servers",
            "id": "test-id",
        }

        request = ListServersRequest.from_dict(data)

        assert request.id == "test-id"
        assert request.method == "list_servers"

    def test_auto_generates_id(self) -> None:
        """Test that id is auto-generated if not provided."""
        request = ListServersRequest()

        assert request.id is not None
        assert len(request.id) > 0

    def test_from_dict_empty_id_generates_new_id(self) -> None:
        """Test that empty string id triggers auto-generation."""
        data = {"method": "list_servers", "id": ""}

        request = ListServersRequest.from_dict(data)

        assert request.id != ""
        assert len(request.id) > 0

    def test_to_dict(self) -> None:
        """Test to_dict method."""
        request = ListServersRequest(id="test-id")

        data = request.to_dict()

        assert data["method"] == "list_servers"
        assert data["id"] == "test-id"


class TestListToolsRequest:
    """Tests for ListToolsRequest."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        request = ListToolsRequest(server="test-server", id="test-id")

        json_str = request.to_json()
        data = json.loads(json_str)

        assert data["method"] == "list_tools"
        assert data["server"] == "test-server"
        assert data["id"] == "test-id"

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "method": "list_tools",
            "server": "test-server",
            "id": "test-id",
        }

        request = ListToolsRequest.from_dict(data)

        assert request.server == "test-server"
        assert request.id == "test-id"

    def test_from_dict_missing_server_raises(self) -> None:
        """Raise ValueError when server is missing."""
        data = {"method": "list_tools", "id": "test-id"}

        with pytest.raises(ValueError, match="Missing 'server' in list_tools request"):
            ListToolsRequest.from_dict(data)


class TestGetServerToolRequest:
    """Tests for GetServerToolRequest."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        request = GetServerToolRequest(server="test-server", tool_name="test-tool", id="test-id")

        json_str = request.to_json()
        data = json.loads(json_str)

        assert data["method"] == "get_server_tool"
        assert data["server"] == "test-server"
        assert data["tool_name"] == "test-tool"
        assert data["id"] == "test-id"

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "method": "get_server_tool",
            "server": "test-server",
            "tool_name": "test-tool",
            "id": "test-id",
        }

        request = GetServerToolRequest.from_dict(data)

        assert request.server == "test-server"
        assert request.tool_name == "test-tool"
        assert request.id == "test-id"

    def test_from_dict_missing_server_raises(self) -> None:
        """Raise ValueError when server is missing."""
        data = {"method": "get_server_tool", "tool_name": "test-tool", "id": "test-id"}

        with pytest.raises(ValueError, match="Missing 'server' in get_server_tool request"):
            GetServerToolRequest.from_dict(data)

    def test_from_dict_missing_tool_name_raises(self) -> None:
        """Raise ValueError when tool_name is missing."""
        data = {"method": "get_server_tool", "server": "test-server", "id": "test-id"}

        with pytest.raises(ValueError, match="Missing 'tool_name' in get_server_tool request"):
            GetServerToolRequest.from_dict(data)


class TestCallToolRequest:
    """Tests for CallToolRequest."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        request = CallToolRequest(
            server="test-server",
            tool="test-tool",
            arguments={"key": "value"},
            timeout_seconds=60.0,
            id="test-id",
        )

        json_str = request.to_json()
        data = json.loads(json_str)

        assert data["method"] == "call_tool"
        assert data["server"] == "test-server"
        assert data["tool"] == "test-tool"
        assert data["arguments"] == {"key": "value"}
        assert data["timeout_seconds"] == 60.0
        assert data["id"] == "test-id"

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "method": "call_tool",
            "server": "test-server",
            "tool": "test-tool",
            "arguments": {"arg": "val"},
            "timeout_seconds": 45.0,
            "id": "test-id",
        }

        request = CallToolRequest.from_dict(data)

        assert request.server == "test-server"
        assert request.tool == "test-tool"
        assert request.arguments == {"arg": "val"}
        assert request.timeout_seconds == 45.0
        assert request.id == "test-id"

    def test_from_dict_defaults(self) -> None:
        """Test creation with default values."""
        data = {
            "method": "call_tool",
            "server": "test-server",
            "tool": "test-tool",
        }

        request = CallToolRequest.from_dict(data)

        assert request.arguments == {}
        assert request.timeout_seconds == 30.0

    def test_from_dict_explicit_none_normalized_to_defaults(self) -> None:
        """Test that explicit None values are normalized to defaults."""
        data = {
            "method": "call_tool",
            "server": "test-server",
            "tool": "test-tool",
            "arguments": None,
            "timeout_seconds": None,
        }

        request = CallToolRequest.from_dict(data)

        assert request.arguments == {}
        assert request.timeout_seconds == 30.0

    def test_from_dict_preserves_falsy_values(self) -> None:
        """Test that explicit falsy values (0, empty dict) are preserved."""
        data = {
            "method": "call_tool",
            "server": "test-server",
            "tool": "test-tool",
            "arguments": {},
            "timeout_seconds": 0,
        }

        request = CallToolRequest.from_dict(data)

        assert request.arguments == {}
        assert request.timeout_seconds == 0

    def test_from_dict_missing_server_raises(self) -> None:
        """Raise ValueError when server is missing."""
        data = {"method": "call_tool", "tool": "test-tool"}

        with pytest.raises(ValueError, match="Missing 'server' in call_tool request"):
            CallToolRequest.from_dict(data)

    def test_from_dict_missing_tool_raises(self) -> None:
        """Raise ValueError when tool is missing."""
        data = {"method": "call_tool", "server": "test-server"}

        with pytest.raises(ValueError, match="Missing 'tool' in call_tool request"):
            CallToolRequest.from_dict(data)

    def test_from_dict_invalid_timeout_seconds_raises(self) -> None:
        """Raise ValueError when timeout_seconds is not a valid number."""
        data = {
            "method": "call_tool",
            "server": "test-server",
            "tool": "test-tool",
            "timeout_seconds": "not-a-number",
        }

        with pytest.raises(ValueError, match="Invalid 'timeout_seconds' value"):
            CallToolRequest.from_dict(data)

    def test_from_dict_timeout_seconds_coerced_to_float(self) -> None:
        """Test that timeout_seconds is coerced to float."""
        data = {
            "method": "call_tool",
            "server": "test-server",
            "tool": "test-tool",
            "timeout_seconds": "45",
        }

        request = CallToolRequest.from_dict(data)

        assert request.timeout_seconds == 45.0
        assert isinstance(request.timeout_seconds, float)


class TestHealthRequest:
    """Tests for HealthRequest."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        request = HealthRequest(id="test-id")

        json_str = request.to_json()
        data = json.loads(json_str)

        assert data["method"] == "health"
        assert data["id"] == "test-id"

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {"method": "health", "id": "test-id"}

        request = HealthRequest.from_dict(data)

        assert request.id == "test-id"
        assert request.method == "health"


class TestServerInfo:
    """Tests for ServerInfo."""

    def test_to_dict(self) -> None:
        """Test to_dict matches Pydantic model_dump()."""
        info = ServerInfo(name="firecrawl", transport="stdio", healthy=True)

        data = info.to_dict()

        assert data == {"name": "firecrawl", "transport": "stdio", "healthy": True}

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {"name": "linear", "transport": "sse", "healthy": False}

        info = ServerInfo.from_dict(data)

        assert info.name == "linear"
        assert info.transport == "sse"
        assert info.healthy is False

    def test_from_dict_missing_name_raises(self) -> None:
        """Raise ValueError when name is missing."""
        data = {"transport": "stdio", "healthy": True}

        with pytest.raises(ValueError, match="Missing required field 'name' for ServerInfo"):
            ServerInfo.from_dict(data)

    def test_from_dict_missing_transport_raises(self) -> None:
        """Raise ValueError when transport is missing."""
        data = {"name": "server1", "healthy": True}

        with pytest.raises(ValueError, match="Missing required field 'transport' for ServerInfo"):
            ServerInfo.from_dict(data)

    def test_from_dict_missing_healthy_raises(self) -> None:
        """Raise ValueError when healthy is missing."""
        data = {"name": "server1", "transport": "stdio"}

        with pytest.raises(ValueError, match="Missing required field 'healthy' for ServerInfo"):
            ServerInfo.from_dict(data)


class TestServersResponse:
    """Tests for ServersResponse."""

    def test_to_dict(self) -> None:
        """Test to_dict matches Pydantic model_dump()."""
        response = ServersResponse(
            servers=[
                ServerInfo(name="server1", transport="stdio", healthy=True),
                ServerInfo(name="server2", transport="sse", healthy=False),
            ]
        )

        data = response.to_dict()

        assert data == {
            "servers": [
                {"name": "server1", "transport": "stdio", "healthy": True},
                {"name": "server2", "transport": "sse", "healthy": False},
            ]
        }

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "servers": [
                {"name": "s1", "transport": "stdio", "healthy": True},
            ]
        }

        response = ServersResponse.from_dict(data)

        assert len(response.servers) == 1
        assert response.servers[0].name == "s1"


class TestMCPCallResponse:
    """Tests for MCPCallResponse."""

    def test_to_dict(self) -> None:
        """Test to_dict matches Pydantic model_dump()."""
        response = MCPCallResponse(result={"output": "data"})

        data = response.to_dict()

        assert data == {"result": {"output": "data"}}

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {"result": {"key": "val"}}

        response = MCPCallResponse.from_dict(data)

        assert response.result == {"key": "val"}


class TestHealthResponse:
    """Tests for HealthResponse."""

    def test_to_dict_healthy(self) -> None:
        """Test to_dict for healthy status."""
        response = HealthResponse(status="ok", provider="running")

        data = response.to_dict()

        assert data == {"status": "ok", "provider": "running"}

    def test_to_dict_degraded(self) -> None:
        """Test to_dict for degraded status."""
        response = HealthResponse(status="degraded", provider="down")

        data = response.to_dict()

        assert data == {"status": "degraded", "provider": "down"}

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {"status": "ok", "provider": "running"}

        response = HealthResponse.from_dict(data)

        assert response.status == "ok"
        assert response.provider == "running"

    def test_from_dict_default_provider(self) -> None:
        """Test that provider defaults to 'running'."""
        data = {"status": "ok"}

        response = HealthResponse.from_dict(data)

        assert response.provider == "running"

    def test_from_dict_missing_status_raises(self) -> None:
        """Raise ValueError when status is missing."""
        data = {"provider": "running"}

        with pytest.raises(ValueError, match="Missing required field 'status' for HealthResponse"):
            HealthResponse.from_dict(data)


class TestErrorType:
    """Tests for ErrorType enum."""

    def test_all_error_types_serialize_as_strings(self) -> None:
        """Verify all error types serialize to stable string values."""
        expected = {
            ErrorType.BAD_REQUEST: "BAD_REQUEST",
            ErrorType.NOT_FOUND: "NOT_FOUND",
            ErrorType.JSONRPC_ERROR: "JSONRPC_ERROR",
            ErrorType.TIMEOUT: "TIMEOUT",
            ErrorType.BUSY: "BUSY",
            ErrorType.PROVIDER_CRASHED: "PROVIDER_CRASHED",
            ErrorType.INTERNAL: "INTERNAL",
        }

        for error_type, expected_str in expected.items():
            assert error_type.value == expected_str

    def test_error_type_from_string(self) -> None:
        """Test creating ErrorType from string."""
        assert ErrorType("BAD_REQUEST") == ErrorType.BAD_REQUEST
        assert ErrorType("TIMEOUT") == ErrorType.TIMEOUT


class TestErrorDetail:
    """Tests for ErrorDetail."""

    def test_to_dict(self) -> None:
        """Test to_dict matching Pydantic model_dump()."""
        error = ErrorDetail(
            type=ErrorType.TIMEOUT,
            message="Request timed out",
            details={"elapsed_ms": 30000},
        )

        data = error.to_dict()

        assert data == {
            "type": "TIMEOUT",
            "message": "Request timed out",
            "details": {"elapsed_ms": 30000},
        }

    def test_to_dict_without_details(self) -> None:
        """Test to_dict when details is None."""
        error = ErrorDetail(
            type=ErrorType.NOT_FOUND,
            message="Server not found",
        )

        data = error.to_dict()

        assert data == {
            "type": "NOT_FOUND",
            "message": "Server not found",
            "details": None,
        }

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "type": "BUSY",
            "message": "Provider busy",
            "details": {"retry_after_ms": 1000},
        }

        error = ErrorDetail.from_dict(data)

        assert error.type == ErrorType.BUSY
        assert error.message == "Provider busy"
        assert error.details == {"retry_after_ms": 1000}

    def test_from_dict_missing_type_raises(self) -> None:
        """Raise ValueError when type is missing."""
        data = {"message": "Error"}

        with pytest.raises(ValueError, match="Missing 'type' in error detail"):
            ErrorDetail.from_dict(data)

    def test_from_dict_missing_message_raises(self) -> None:
        """Raise ValueError when message is missing."""
        data = {"type": "INTERNAL"}

        with pytest.raises(ValueError, match="Missing 'message' in error detail"):
            ErrorDetail.from_dict(data)

    def test_from_dict_invalid_details_raises(self) -> None:
        """Raise ValueError when details is not a dict or null."""
        data = {"type": "INTERNAL", "message": "Error", "details": "not a dict"}

        with pytest.raises(
            ValueError, match="Invalid 'details' in error detail; expected dict or null"
        ):
            ErrorDetail.from_dict(data)

    def test_from_dict_list_details_raises(self) -> None:
        """Raise ValueError when details is a list instead of dict."""
        data = {"type": "INTERNAL", "message": "Error", "details": ["item1", "item2"]}

        with pytest.raises(
            ValueError, match="Invalid 'details' in error detail; expected dict or null"
        ):
            ErrorDetail.from_dict(data)

    def test_from_dict_invalid_type_raises(self) -> None:
        """Raise TypeError when type is neither a string nor ErrorType."""
        data = {"type": 123, "message": "Error"}

        with pytest.raises(
            TypeError, match="Invalid 'type' in error detail; expected ErrorType or string"
        ):
            ErrorDetail.from_dict(data)


class TestSuccessEnvelope:
    """Tests for SuccessEnvelope."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        envelope = SuccessEnvelope(
            id="test-id",
            result={"servers": [{"name": "test", "transport": "stdio", "healthy": True}]},
        )

        json_str = envelope.to_json()
        data = json.loads(json_str)

        assert data["id"] == "test-id"
        assert data["status"] == "success"
        assert data["result"]["servers"][0]["name"] == "test"

    def test_to_dict(self) -> None:
        """Test to_dict method."""
        envelope = SuccessEnvelope(id="test-id", result={"key": "value"})

        data = envelope.to_dict()

        assert data == {
            "id": "test-id",
            "status": "success",
            "result": {"key": "value"},
        }

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "id": "test-id",
            "status": "success",
            "result": {"output": "data"},
        }

        envelope = SuccessEnvelope.from_dict(data)

        assert envelope.id == "test-id"
        assert envelope.result == {"output": "data"}

    def test_from_dict_missing_id_raises(self) -> None:
        """Raise ValueError when id is missing."""
        data = {"status": "success", "result": {}}

        with pytest.raises(ValueError, match="Missing 'id' in success envelope"):
            SuccessEnvelope.from_dict(data)


class TestErrorEnvelope:
    """Tests for ErrorEnvelope."""

    def test_serialization(self) -> None:
        """Test JSON serialization."""
        envelope = ErrorEnvelope(
            id="test-id",
            error=ErrorDetail(
                type=ErrorType.TIMEOUT,
                message="Timed out",
                details={"timeout_seconds": 30},
            ),
        )

        json_str = envelope.to_json()
        data = json.loads(json_str)

        assert data["id"] == "test-id"
        assert data["status"] == "error"
        assert data["error"]["type"] == "TIMEOUT"
        assert data["error"]["message"] == "Timed out"
        assert data["error"]["details"] == {"timeout_seconds": 30}

    def test_to_dict(self) -> None:
        """Test to_dict method."""
        envelope = ErrorEnvelope(
            id="test-id",
            error=ErrorDetail(
                type=ErrorType.NOT_FOUND,
                message="Not found",
            ),
        )

        data = envelope.to_dict()

        assert data == {
            "id": "test-id",
            "status": "error",
            "error": {
                "type": "NOT_FOUND",
                "message": "Not found",
                "details": None,
            },
        }

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "id": "test-id",
            "status": "error",
            "error": {
                "type": "INTERNAL",
                "message": "Internal error",
            },
        }

        envelope = ErrorEnvelope.from_dict(data)

        assert envelope.id == "test-id"
        assert envelope.error.type == ErrorType.INTERNAL
        assert envelope.error.message == "Internal error"

    def test_from_dict_missing_id_raises(self) -> None:
        """Raise ValueError when id is missing."""
        data = {
            "status": "error",
            "error": {"type": "INTERNAL", "message": "Error"},
        }

        with pytest.raises(ValueError, match="Missing 'id' in error envelope"):
            ErrorEnvelope.from_dict(data)

    def test_from_dict_missing_error_raises(self) -> None:
        """Raise ValueError when error is missing."""
        data = {"id": "test-id", "status": "error"}

        with pytest.raises(ValueError, match="Missing 'error' in error envelope"):
            ErrorEnvelope.from_dict(data)


class TestParseRequest:
    """Tests for parse_request function."""

    def test_parse_list_servers_request(self) -> None:
        """Parse a list_servers request."""
        data = json.dumps({"method": "list_servers", "id": "test-id"})

        request = parse_request(data)

        assert isinstance(request, ListServersRequest)
        assert request.id == "test-id"

    def test_parse_list_tools_request(self) -> None:
        """Parse a list_tools request."""
        data = json.dumps({"method": "list_tools", "server": "test-server", "id": "test-id"})

        request = parse_request(data)

        assert isinstance(request, ListToolsRequest)
        assert request.server == "test-server"

    def test_parse_get_server_tool_request(self) -> None:
        """Parse a get_server_tool request."""
        data = json.dumps(
            {
                "method": "get_server_tool",
                "server": "test-server",
                "tool_name": "test-tool",
                "id": "test-id",
            }
        )

        request = parse_request(data)

        assert isinstance(request, GetServerToolRequest)
        assert request.server == "test-server"
        assert request.tool_name == "test-tool"

    def test_parse_call_tool_request(self) -> None:
        """Parse a call_tool request."""
        data = json.dumps(
            {
                "method": "call_tool",
                "server": "test-server",
                "tool": "test-tool",
                "arguments": {"key": "value"},
                "timeout_seconds": 60.0,
                "id": "test-id",
            }
        )

        request = parse_request(data)

        assert isinstance(request, CallToolRequest)
        assert request.server == "test-server"
        assert request.tool == "test-tool"
        assert request.arguments == {"key": "value"}
        assert request.timeout_seconds == 60.0

    def test_parse_health_request(self) -> None:
        """Parse a health request."""
        data = json.dumps({"method": "health", "id": "test-id"})

        request = parse_request(data)

        assert isinstance(request, HealthRequest)

    def test_parse_from_dict(self) -> None:
        """Parse from a dictionary directly."""
        data = {"method": "list_servers", "id": "test-id"}

        request = parse_request(data)

        assert isinstance(request, ListServersRequest)

    def test_invalid_json_raises_error(self) -> None:
        """Raise ValueError for invalid JSON."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_request("not json")

    def test_unknown_method_raises_error(self) -> None:
        """Raise ValueError for unknown method."""
        data = json.dumps({"method": "unknown"})

        with pytest.raises(ValueError, match="Unknown method"):
            parse_request(data)

    def test_non_object_json_raises_error(self) -> None:
        """Raise TypeError when JSON is not an object."""
        with pytest.raises(TypeError, match="expected JSON object"):
            parse_request('"just a string"')

        with pytest.raises(TypeError, match="expected JSON object"):
            parse_request("[1, 2, 3]")

    def test_missing_method_raises_error(self) -> None:
        """Raise ValueError when method field is missing."""
        data = json.dumps({"server": "test", "id": "test"})

        with pytest.raises(ValueError, match="Missing required field: 'method'"):
            parse_request(data)

    def test_parse_request_ignores_extra_fields(self) -> None:
        """Extra fields in request JSON should be ignored."""
        data = json.dumps(
            {
                "method": "health",
                "id": "test-id",
                "unknown_field": "should be ignored",
            }
        )

        request = parse_request(data)

        assert isinstance(request, HealthRequest)
        assert request.id == "test-id"


class TestParseResponse:
    """Tests for parse_response function."""

    def test_parse_success_response(self) -> None:
        """Parse a success response."""
        data = json.dumps(
            {
                "id": "test-id",
                "status": "success",
                "result": {"key": "value"},
            }
        )

        response = parse_response(data)

        assert isinstance(response, SuccessEnvelope)
        assert response.id == "test-id"
        assert response.result == {"key": "value"}

    def test_parse_error_response(self) -> None:
        """Parse an error response."""
        data = json.dumps(
            {
                "id": "test-id",
                "status": "error",
                "error": {
                    "type": "TIMEOUT",
                    "message": "Request timed out",
                    "details": {"elapsed_ms": 30000},
                },
            }
        )

        response = parse_response(data)

        assert isinstance(response, ErrorEnvelope)
        assert response.id == "test-id"
        assert response.error.type == ErrorType.TIMEOUT
        assert response.error.message == "Request timed out"

    def test_parse_from_dict(self) -> None:
        """Parse from a dictionary directly."""
        data = {"id": "test-id", "status": "success", "result": {}}

        response = parse_response(data)

        assert isinstance(response, SuccessEnvelope)

    def test_invalid_json_raises_error(self) -> None:
        """Raise ValueError for invalid JSON."""
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_response("not json")

    def test_unknown_status_raises_error(self) -> None:
        """Raise ValueError for unknown status."""
        data = json.dumps({"id": "test", "status": "unknown"})

        with pytest.raises(ValueError, match="Unknown status"):
            parse_response(data)

    def test_non_object_json_raises_error(self) -> None:
        """Raise TypeError when JSON is not an object."""
        with pytest.raises(TypeError, match="expected JSON object"):
            parse_response('"just a string"')

    def test_missing_status_raises_error(self) -> None:
        """Raise ValueError when status field is missing."""
        data = json.dumps({"id": "test-id", "result": {}})

        with pytest.raises(ValueError, match="Missing required field: 'status'"):
            parse_response(data)


class TestToJson:
    """Tests for to_json function."""

    def test_to_json_success_envelope(self) -> None:
        """Serialize a success envelope."""
        envelope = SuccessEnvelope(id="test-id", result={"key": "value"})

        json_str = to_json(envelope)
        data = json.loads(json_str)

        assert data["id"] == "test-id"
        assert data["status"] == "success"
        assert data["result"] == {"key": "value"}

    def test_to_json_error_envelope(self) -> None:
        """Serialize an error envelope."""
        envelope = ErrorEnvelope(
            id="test-id",
            error=ErrorDetail(type=ErrorType.INTERNAL, message="Error"),
        )

        json_str = to_json(envelope)
        data = json.loads(json_str)

        assert data["id"] == "test-id"
        assert data["status"] == "error"
        assert data["error"]["type"] == "INTERNAL"


class TestCreateSuccessResponse:
    """Tests for create_success_response helper."""

    def test_create_success_response(self) -> None:
        """Create a success response envelope."""
        envelope = create_success_response(
            request_id="test-id",
            result={"output": "data"},
        )

        assert envelope.id == "test-id"
        assert envelope.status == "success"
        assert envelope.result == {"output": "data"}


class TestCreateErrorResponse:
    """Tests for create_error_response helper."""

    def test_create_error_response(self) -> None:
        """Create an error response envelope."""
        envelope = create_error_response(
            request_id="test-id",
            error_type=ErrorType.TIMEOUT,
            message="Timed out",
            details={"elapsed": 30},
        )

        assert envelope.id == "test-id"
        assert envelope.status == "error"
        assert envelope.error.type == ErrorType.TIMEOUT
        assert envelope.error.message == "Timed out"
        assert envelope.error.details == {"elapsed": 30}

    def test_create_error_response_without_details(self) -> None:
        """Create an error response without details."""
        envelope = create_error_response(
            request_id="test-id",
            error_type=ErrorType.NOT_FOUND,
            message="Not found",
        )

        assert envelope.error.details is None


class TestJSONCompatibilityWithPydanticSchemas:
    """Tests to ensure JSON output matches Pydantic schemas exactly."""

    def test_servers_response_matches_pydantic(self) -> None:
        """ServersResponse.to_dict() produces same structure as Pydantic model_dump()."""
        servers_response = ServersResponse(
            servers=[
                ServerInfo(name="server1", transport="stdio", healthy=True),
                ServerInfo(name="server2", transport="sse", healthy=False),
            ]
        )

        # Expected structure from Pydantic model_dump()
        expected = {
            "servers": [
                {"name": "server1", "transport": "stdio", "healthy": True},
                {"name": "server2", "transport": "sse", "healthy": False},
            ]
        }

        assert servers_response.to_dict() == expected

    def test_mcp_call_response_matches_pydantic(self) -> None:
        """MCPCallResponse.to_dict() produces same structure as Pydantic model_dump()."""
        call_response = MCPCallResponse(result={"output": "test data"})

        expected = {"result": {"output": "test data"}}

        assert call_response.to_dict() == expected

    def test_health_response_matches_pydantic(self) -> None:
        """HealthResponse.to_dict() produces same structure as Pydantic model_dump()."""
        health_response = HealthResponse(status="ok", provider="running")

        expected = {"status": "ok", "provider": "running"}

        assert health_response.to_dict() == expected

    def test_error_envelope_matches_pydantic(self) -> None:
        """Error response structure matches Pydantic ErrorEnvelope."""
        error_envelope = ErrorEnvelope(
            id="test-id",
            error=ErrorDetail(
                type=ErrorType.BUSY,
                message="Provider is busy",
                details={"retry_after_ms": 1000},
            ),
        )

        expected = {
            "id": "test-id",
            "status": "error",
            "error": {
                "type": "BUSY",
                "message": "Provider is busy",
                "details": {"retry_after_ms": 1000},
            },
        }

        assert error_envelope.to_dict() == expected
