"""Custom middleware implementations for the FastAPI application."""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from starlette.datastructures import MutableHeaders

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

HTTP_RESPONSE_START = "http.response.start"
HSTS_HEADER_VALUE = "max-age=31536000; includeSubDomains"
REQUEST_ID_HEADER = "X-Request-ID"


class SecurityHeadersMiddleware:
    """Attach standard security headers to all HTTP responses."""

    def __init__(self, app: ASGIApp, *, enforce_https: bool = False) -> None:
        """Store downstream app and HTTPS enforcement flag."""
        self.app = app
        self.enforce_https = enforce_https

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Wrap the send callable to inject security headers on HTTP responses."""
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message.get("type") == HTTP_RESPONSE_START:
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
                if self._should_add_hsts(scope):
                    headers["Strict-Transport-Security"] = HSTS_HEADER_VALUE
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _should_add_hsts(self, scope: Scope) -> bool:
        scheme = scope.get("scheme", "").lower()
        return self.enforce_https and scheme == "https"


class RequestIDMiddleware:
    """Generate or propagate a unique request ID for each incoming request.

    The request ID is attached to the ASGI scope under the key ``request_id`` and
    included in the response headers as ``X-Request-ID``. If an incoming request
    already contains an ``X-Request-ID`` header, that value is propagated instead
    of generating a new one.

    Configuration:
        No additional configuration required. Enable via ``enable_request_id``
        setting in ``Settings``.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Store downstream app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Attach request ID to scope and response headers."""
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._extract_or_generate_id(scope)
        scope["request_id"] = request_id

        async def send_wrapper(message: Message) -> None:
            if message.get("type") == HTTP_RESPONSE_START:
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _extract_or_generate_id(scope: Scope) -> str:
        raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        headers = dict(raw_headers)
        existing_id = headers.get(REQUEST_ID_HEADER.lower().encode())
        if existing_id:
            return existing_id.decode("utf-8", errors="replace")
        return str(uuid.uuid4())


class RequestLoggingMiddleware:
    """Log request method, path, status code, and latency for each HTTP request.

    Uses structured logging with key-value pairs for easy querying. Exceptions
    are logged and re-raised to preserve the exception handling chain.

    Configuration:
        No additional configuration required. Enable via ``enable_request_logging``
        setting in ``Settings``.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Store downstream app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Log request details and timing."""
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        request_id = scope.get("request_id", "-")
        status_code: int | None = None
        start_time = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message.get("type") == HTTP_RESPONSE_START:
                status_code = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "Request failed",
                extra={
                    "method": method,
                    "path": path,
                    "request_id": request_id,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "Request completed",
            extra={
                "method": method,
                "path": path,
                "status_code": status_code,
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
            },
        )


class MetricsMiddleware:
    """Collect request metrics including duration and status code counts.

    Exposes an in-memory metrics registry accessible via ``app.state.metrics``.
    Metrics are organized by route pattern and status code for aggregation.

    Configuration:
        No additional configuration required. Enable via ``enable_metrics``
        setting in ``Settings``. Access metrics via ``app.state.metrics``.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Store downstream app and initialize metrics registry."""
        self.app = app
        self.request_count: dict[str, int] = defaultdict(int)
        self.request_duration_sum: dict[str, float] = defaultdict(float)
        self.status_counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Record request metrics."""
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        method = scope.get("method", "UNKNOWN")
        route_key = f"{method} {path}"
        status_code: int = 0
        start_time = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message.get("type") == HTTP_RESPONSE_START:
                status_code = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start_time
            self.request_count[route_key] += 1
            self.request_duration_sum[route_key] += duration
            self.status_counts[route_key][status_code] += 1

    def get_metrics(self) -> dict[str, Any]:
        """Return current metrics snapshot."""
        return {
            "request_count": dict(self.request_count),
            "request_duration_sum": dict(self.request_duration_sum),
            "status_counts": {k: dict(v) for k, v in self.status_counts.items()},
        }


class RateLimitingMiddleware:
    """Per-IP fixed-window rate limiter that rejects requests with 429 when exceeded.

    Implements a simple fixed-window algorithm where each IP is allowed a maximum
    number of requests within a configurable time window. When the limit is
    exceeded, subsequent requests receive a 429 Too Many Requests response.

    Configuration:
        - ``rate_limit_requests``: Maximum requests per window (default: 100)
        - ``rate_limit_window_seconds``: Window duration in seconds (default: 60)
        Enable via ``enable_rate_limiting`` setting in ``Settings``.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_window: int = 100,
        window_seconds: int = 60,
    ) -> None:
        """Store downstream app and rate limit configuration."""
        if requests_per_window <= 0:
            raise ValueError("requests_per_window must be a positive integer")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be a positive integer")
        self.app = app
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._window_start: dict[str, float] = {}
        self._request_counts: dict[str, int] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check rate limit and either proceed or reject with 429."""
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        client_ip = self._get_client_ip(scope)
        current_time = time.monotonic()

        if self._is_rate_limited(client_ip, current_time):
            await self._send_rate_limit_response(send)
            return

        self._record_request(client_ip, current_time)
        await self.app(scope, receive, send)

    @staticmethod
    def _get_client_ip(scope: Scope) -> str:
        client: tuple[str, int] | None = scope.get("client")
        if client:
            return client[0]
        return "unknown"

    def _is_rate_limited(self, client_ip: str, current_time: float) -> bool:
        window_start = self._window_start.get(client_ip, 0)
        if current_time - window_start >= self.window_seconds:
            return False
        count = self._request_counts.get(client_ip, 0)
        return count >= self.requests_per_window

    def _record_request(self, client_ip: str, current_time: float) -> None:
        window_start = self._window_start.get(client_ip, 0)
        if current_time - window_start >= self.window_seconds:
            self._window_start[client_ip] = current_time
            self._request_counts[client_ip] = 1
        else:
            self._request_counts[client_ip] = self._request_counts.get(client_ip, 0) + 1

    async def _send_rate_limit_response(self, send: Send) -> None:
        await send(
            {
                "type": HTTP_RESPONSE_START,
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(self.window_seconds).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"detail":"Rate limit exceeded. Please try again later."}',
            }
        )
