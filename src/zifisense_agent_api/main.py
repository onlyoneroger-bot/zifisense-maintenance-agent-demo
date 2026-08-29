from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from zifisense_agent_api.adapters.fixtures import FixtureCatalog
from zifisense_agent_api.application.agent_facade import AgentFacade
from zifisense_agent_api.application.evaluation_service import EvaluationService
from zifisense_agent_api.config import Settings
from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.infrastructure.auth import ApiKeyAuthenticator
from zifisense_agent_api.infrastructure.database import Database
from zifisense_agent_api.infrastructure.rate_limit import SlidingWindowRateLimiter
from zifisense_agent_api.infrastructure.repositories import EvaluationRepository
from zifisense_agent_api.transport.errors import (
    application_error_handler,
    error_response,
    http_error_handler,
    validation_error_handler,
)
from zifisense_agent_api.transport.routers import agent, evaluation, system


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], float] | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    database = Database(app_settings.database_url)
    database.create_schema()
    repository = EvaluationRepository(database)
    fixtures = FixtureCatalog(app_settings.fixture_dir)

    app = FastAPI(
        title="ZiFiSense Intelligent Maintenance Agent API",
        version=app_settings.app_version,
        description="Competition evaluation API — Sprint 1 callable subset.",
        openapi_version="3.1.0",
    )
    app.state.settings = app_settings
    app.state.database = database
    app.state.fixtures = fixtures
    app.state.authenticator = ApiKeyAuthenticator(app_settings)
    app.state.rate_limiter = SlidingWindowRateLimiter(clock=clock)
    app.state.evaluation_service = EvaluationService(repository, fixtures)
    app.state.agent_facade = AgentFacade(repository)
    app.state.repository = repository

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied_request_id = request.headers.get("X-Request-ID")
        request.state.trace_id = f"trace_{uuid.uuid4().hex}"
        if supplied_request_id is None:
            request.state.request_id = f"req_{uuid.uuid4().hex}"
        elif len(supplied_request_id) > 128:
            request.state.request_id = f"req_{uuid.uuid4().hex}"
            return error_response(
                request,
                ApplicationError(
                    400,
                    "INVALID_REQUEST",
                    "X-Request-ID must not exceed 128 characters.",
                    details={"header": "X-Request-ID", "max_length": 128},
                ),
            )
        else:
            request.state.request_id = supplied_request_id
        return await call_next(request)

    app.add_exception_handler(ApplicationError, application_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)

    app.include_router(system.router)
    app.include_router(evaluation.router)
    app.include_router(agent.router)
    return app


app = create_app()
