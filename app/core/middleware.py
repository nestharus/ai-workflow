"""Custom middleware implementations for the FastAPI application."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

HSTS_HEADER_VALUE = "max-age=31536000; includeSubDomains"


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
            if message.get("type") == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                if self._should_add_hsts(scope):
                    headers["Strict-Transport-Security"] = HSTS_HEADER_VALUE
            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _should_add_hsts(self, scope: Scope) -> bool:
        scheme = scope.get("scheme", "").lower()
        return self.enforce_https and scheme == "https"
