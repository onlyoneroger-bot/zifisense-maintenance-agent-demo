from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from zifisense_agent_api.infrastructure.auth import ApiKeyAuthenticator
from zifisense_agent_api.infrastructure.rate_limit import SlidingWindowRateLimiter


class MCPBearerAuthMiddleware:
    """Authenticate the competition's opaque Bearer token before MCP dispatch."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        authenticator: ApiKeyAuthenticator,
        limiter: SlidingWindowRateLimiter,
        total_per_minute: int,
    ) -> None:
        self._app = app
        self._authenticator = authenticator
        self._limiter = limiter
        self._total_per_minute = total_per_minute

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        authorization = headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token:
            await self._error(401, "A valid Bearer API key is required.", scope, receive, send)
            return
        identity = self._authenticator.authenticate(token)
        if identity is None:
            await self._error(401, "The supplied API key is invalid.", scope, receive, send)
            return
        if "mcp:use" not in identity.scopes:
            await self._error(
                403,
                "The client does not have the required MCP scope.",
                scope,
                receive,
                send,
            )
            return
        if not self._limiter.allow(identity.client_id, "mcp", self._total_per_minute):
            await self._error(
                429,
                "The MCP request limit has been exceeded.",
                scope,
                receive,
                send,
                headers={"Retry-After": "1"},
            )
            return
        scope["zifisense.client_id"] = identity.client_id
        await self._app(scope, receive, send)

    @staticmethod
    async def _error(
        status_code: int,
        message: str,
        scope: Scope,
        receive: Receive,
        send: Send,
        headers: dict[str, str] | None = None,
    ) -> None:
        response = JSONResponse(
            {"error": {"status": status_code, "message": message}},
            status_code=status_code,
            headers=headers,
        )
        await response(scope, receive, send)
