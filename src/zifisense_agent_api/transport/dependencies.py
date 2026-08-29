from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.infrastructure.auth import ClientIdentity

bearer_scheme = HTTPBearer(auto_error=False)


def require_client(
    scope: str,
    *,
    agent_bucket: bool = False,
) -> Callable[..., Coroutine[Any, Any, ClientIdentity]]:
    async def dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),  # noqa: B008
    ) -> ClientIdentity:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise ApplicationError(
                401,
                "INVALID_ACCESS_TOKEN",
                "A valid Bearer API key is required.",
            )
        identity = request.app.state.authenticator.authenticate(credentials.credentials)
        if identity is None:
            raise ApplicationError(
                401,
                "INVALID_ACCESS_TOKEN",
                "The supplied API key is invalid.",
            )
        if scope not in identity.scopes:
            raise ApplicationError(
                403,
                "INSUFFICIENT_SCOPE",
                f"The client does not have the required scope: {scope}.",
            )
        settings = request.app.state.settings
        limiter = request.app.state.rate_limiter
        if not limiter.allow(
            identity.client_id,
            "total",
            settings.rate_limit_total_per_minute,
        ):
            raise ApplicationError(
                429,
                "RATE_LIMITED",
                "The client request limit has been exceeded.",
                retryable=True,
            )
        if agent_bucket and not limiter.allow(
            identity.client_id,
            "agent",
            settings.rate_limit_agent_per_minute,
        ):
            raise ApplicationError(
                429,
                "RATE_LIMITED",
                "The Agent invocation limit has been exceeded.",
                retryable=True,
            )
        return identity

    return dependency


def get_request_ids(request: Request) -> tuple[str, str]:
    return request.state.request_id, request.state.trace_id
