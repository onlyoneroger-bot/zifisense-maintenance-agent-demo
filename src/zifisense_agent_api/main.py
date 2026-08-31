from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.exceptions import HTTPException as StarletteHTTPException

from zifisense_agent_api.adapters.asset_fault_catalog import AssetFaultCatalog
from zifisense_agent_api.adapters.fixtures import FixtureCatalog
from zifisense_agent_api.adapters.llm.base import LLMProvider
from zifisense_agent_api.adapters.llm.factory import build_llm_provider
from zifisense_agent_api.application.agent_facade import AgentFacade
from zifisense_agent_api.application.approval_service import ApprovalService
from zifisense_agent_api.application.evaluation_service import EvaluationService
from zifisense_agent_api.application.event_service import EventService
from zifisense_agent_api.application.reset_service import ResetService
from zifisense_agent_api.application.task_service import TaskService
from zifisense_agent_api.config import Settings
from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.infrastructure.auth import ApiKeyAuthenticator
from zifisense_agent_api.infrastructure.database import Database
from zifisense_agent_api.infrastructure.llm_budget_repository import LLMBudgetRepository
from zifisense_agent_api.infrastructure.rate_limit import SlidingWindowRateLimiter
from zifisense_agent_api.infrastructure.repositories import EvaluationRepository
from zifisense_agent_api.mcp_server import build_mcp_server
from zifisense_agent_api.transport.errors import (
    application_error_handler,
    error_response,
    http_error_handler,
    validation_error_handler,
)
from zifisense_agent_api.transport.mcp_auth import MCPBearerAuthMiddleware
from zifisense_agent_api.transport.routers import admin, agent, evaluation, events, system, tasks


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], float] | None = None,
    llm_provider: LLMProvider | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    database = Database(app_settings.database_url)
    database.create_schema()
    repository = EvaluationRepository(database)
    fixtures = FixtureCatalog(app_settings.fixture_dir)
    catalog = AssetFaultCatalog(app_settings.fixture_dir)
    authenticator = ApiKeyAuthenticator(app_settings)
    rate_limiter = SlidingWindowRateLimiter(clock=clock)
    evaluation_service = EvaluationService(repository, fixtures)
    event_service = EventService(repository)
    task_service = TaskService(repository)
    approval_service = ApprovalService(repository)
    reset_service = ResetService(repository)
    llm_budget_repository = LLMBudgetRepository(database) if app_settings.llm_enabled else None
    active_llm_provider = llm_provider or build_llm_provider(
        app_settings,
        llm_budget_repository,
    )
    agent_facade = AgentFacade(repository, catalog, active_llm_provider)
    mcp_server = build_mcp_server(
        app_version=app_settings.app_version,
        authenticator=authenticator,
        catalog=catalog,
        evaluation_service=evaluation_service,
        agent_facade=agent_facade,
        repository=repository,
        event_service=event_service,
        task_service=task_service,
        approval_service=approval_service,
    )
    mcp_http_app = mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=False,
        transport_security=TransportSecuritySettings(
            allowed_hosts=app_settings.mcp_allowed_hosts,
            allowed_origins=app_settings.mcp_allowed_origins,
        ),
    )
    authenticated_mcp_app = MCPBearerAuthMiddleware(
        mcp_http_app,
        authenticator=authenticator,
        limiter=rate_limiter,
        total_per_minute=app_settings.rate_limit_mcp_per_minute,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(
        title="ZiFiSense Intelligent Maintenance Agent API",
        version=app_settings.app_version,
        description="Competition REST API plus MCP Streamable HTTP evaluation service.",
        openapi_version="3.1.0",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.database = database
    app.state.fixtures = fixtures
    app.state.authenticator = authenticator
    app.state.rate_limiter = rate_limiter
    app.state.evaluation_service = evaluation_service
    app.state.event_service = event_service
    app.state.task_service = task_service
    app.state.approval_service = approval_service
    app.state.reset_service = reset_service
    app.state.agent_facade = agent_facade
    app.state.llm_provider = active_llm_provider
    app.state.llm_budget_repository = llm_budget_repository
    app.state.repository = repository
    app.state.catalog = catalog
    app.state.mcp_server = mcp_server

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
    app.include_router(events.router)
    app.include_router(tasks.router)
    app.include_router(admin.router)
    app.mount("/", authenticated_mcp_app, name="mcp")
    return app


app = create_app()
