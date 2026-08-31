from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from zifisense_agent_api.adapters.asset_fault_catalog import AssetFaultCatalog
from zifisense_agent_api.application.agent_facade import AgentFacade
from zifisense_agent_api.application.approval_service import ApprovalService
from zifisense_agent_api.application.evaluation_service import EvaluationService
from zifisense_agent_api.application.event_service import EventService
from zifisense_agent_api.application.guidance_engine import GuidanceEngine
from zifisense_agent_api.application.task_service import TaskService
from zifisense_agent_api.infrastructure.auth import ApiKeyAuthenticator
from zifisense_agent_api.infrastructure.repositories import EvaluationRepository
from zifisense_agent_api.mcp_models import (
    AssetListResult,
    DiagnosisStatus,
    FaultDetailResult,
    FaultHistoryResult,
    FaultListResult,
    FaultStatus,
    FieldMeasurementRequestResult,
    MaintenanceHistoryResult,
    MCPAgentInvokeResult,
    MonitoringStatus,
    MonitoringSummaryResult,
    OperatingContextResult,
    PeerComparisonResult,
    Severity,
    TaskResult,
)
from zifisense_agent_api.transport.schemas import (
    AgentInvokeRequest,
    AlarmRaisedEventRequest,
    AlarmRaisedPayload,
    ApprovalDecisionRequest,
    CreateEvaluationSessionRequest,
    FieldMeasurementCompletedEventRequest,
    FieldMeasurementCompletedPayload,
    WorkOrderCompletedEventRequest,
    WorkOrderCompletedPayload,
)

DetailModule = Literal[
    "asset",
    "diagnosis",
    "monitoring",
    "operating_context",
    "maintenance_history",
    "similar_faults",
    "peer_comparison",
    "evidence",
    "conflicts",
    "open_questions",
    "recommended_actions",
    "tool_executions",
    "timeline",
]


def _request_ids() -> tuple[str, str]:
    return f"mcp_req_{uuid.uuid4().hex}", f"trace_{uuid.uuid4().hex}"


def _authenticated_client_id(ctx: Context, authenticator: ApiKeyAuthenticator) -> str:
    """Resolve the trusted deployment identity from this MCP request's Bearer token."""

    request = ctx.request_context.request
    headers = getattr(request, "headers", {})
    authorization = headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise ToolError("The authenticated MCP client identity is unavailable.")
    identity = authenticator.authenticate(token)
    if identity is None or "mcp:use" not in identity.scopes:
        raise ToolError("The authenticated MCP client identity is invalid.")
    return identity.client_id


def build_mcp_server(
    *,
    app_version: str,
    authenticator: ApiKeyAuthenticator,
    catalog: AssetFaultCatalog,
    evaluation_service: EvaluationService,
    agent_facade: AgentFacade,
    repository: EvaluationRepository,
    event_service: EventService,
    task_service: TaskService,
    approval_service: ApprovalService,
) -> MCPServer:
    guidance_engine = GuidanceEngine()
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    write_idempotent = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    write_once = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
    server = MCPServer(
        name="zifisense-intelligent-maintenance-agent",
        version=app_version,
        instructions=(
            "纵行科技智能运维比赛 Agent。所有目录和闭环数据均为模拟数据。先用 "
            "list_current_faults 按严重度筛查，再读取 get_fault_detail；处置前应按证据缺口补查"
            "监测、工况、维修史和同类设备。自然语言会话使用 agent_invoke。查询不得被解释为"
            "最终工程结论；补测必须显式同意，工单必须通过证据门控和一次性人工审批。停机、"
            "停线和降载仅提供证据化决策支持，本服务没有 PLC/DCS 或生产控制工具。每次调用后"
            "应读取 structuredContent.guidance，按 next_steps 顺序继续，并优先询问 "
            "blocking_questions。"
        ),
    )

    @server.tool(
        title="创建调查会话",
        description=(
            "从内置场景或一个活动 fault_id 创建隔离调查会话；创建后用 agent_invoke "
            "开始证据调查。scenario_id 与 fault_id 必须且只能提供一个。"
        ),
        annotations=write_idempotent,
    )
    def create_evaluation_session(
        ctx: Context,
        idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
        scenario_id: Literal["reducer_gear_alarm_v1"] | None = None,
        fault_id: str | None = None,
        locale: str = "zh-CN",
    ) -> dict[str, Any]:
        """Create an isolated investigation from one scenario or current catalog fault."""
        request_id, trace_id = _request_ids()
        client_id = _authenticated_client_id(ctx, authenticator)
        try:
            if (scenario_id is None) == (fault_id is None):
                raise ToolError("Exactly one of scenario_id or fault_id must be provided.")
            if fault_id is not None:
                fixture = catalog.alarm_fixture_for_fault(fault_id)
                result = evaluation_service.create_from_fixture(
                    fixture=fixture,
                    locale=locale,
                    client_id=client_id,
                    idempotency_key=idempotency_key,
                    request_id=request_id,
                    trace_id=trace_id,
                    request_payload={"fault_id": fault_id, "locale": locale},
                )
            else:
                assert scenario_id is not None
                result = evaluation_service.create(
                    request=CreateEvaluationSessionRequest(scenario_id=scenario_id, locale=locale),
                    client_id=client_id,
                    idempotency_key=idempotency_key,
                    request_id=request_id,
                    trace_id=trace_id,
                )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        payload = result.model_dump(mode="json")
        payload["guidance"] = guidance_engine.for_tool(
            "create_evaluation_session", payload
        ).model_dump(mode="json")
        return payload

    @server.tool(
        title="筛选设备",
        description=(
            "按站点、产线、类型和活动故障筛选模拟设备；结果按最高活动故障严重度排序，"
            "下一步通常调用 list_current_faults。"
        ),
        annotations=read_only,
    )
    def list_assets(
        site_id: str | None = None,
        line_id: str | None = None,
        asset_type: str | None = None,
        monitoring_status: MonitoringStatus | None = None,
        has_active_fault: bool | None = None,
        keyword: str | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> AssetListResult:
        """List simulated equipment with filters, stable sorting and cursor pagination."""
        try:
            result = catalog.list_assets(
                site_id=site_id,
                line_id=line_id,
                asset_type=asset_type,
                monitoring_status=monitoring_status,
                has_active_fault=has_active_fault,
                keyword=keyword,
                cursor=cursor,
                limit=limit,
            )
            return result.model_copy(
                update={"guidance": guidance_engine.for_tool("list_assets", result)}
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        title="筛选活动故障",
        description=(
            "仅列出未关闭活动故障并按严重度排序；先读取最高优先级项，再调用 "
            "get_fault_detail，不要直接给维修结论。"
        ),
        annotations=read_only,
    )
    def list_current_faults(
        site_id: str | None = None,
        line_id: str | None = None,
        asset_id: str | None = None,
        severity: list[Severity] | None = None,
        fault_status: list[FaultStatus] | None = None,
        diagnosis_status: list[DiagnosisStatus] | None = None,
        detected_from: datetime | None = None,
        detected_to: datetime | None = None,
        requires_human: bool | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> FaultListResult:
        """List active simulated fault investigations; closed history is never mixed in."""
        try:
            result = catalog.list_current_faults(
                site_id=site_id,
                line_id=line_id,
                asset_id=asset_id,
                severity=severity,
                fault_status=fault_status,
                diagnosis_status=diagnosis_status,
                detected_from=detected_from,
                detected_to=detected_to,
                requires_human=requires_human,
                cursor=cursor,
                limit=limit,
            )
            return result.model_copy(
                update={"guidance": guidance_engine.for_tool("list_current_faults", result)}
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        title="读取故障详情",
        description=(
            "读取单个故障的事实、推断、限制、冲突和缺失证据；按 guidance 决定补查、"
            "现场复测或授权决策。"
        ),
        annotations=read_only,
    )
    def get_fault_detail(
        fault_id: str,
        include: list[DetailModule] | None = None,
        history_limit: Annotated[int, Field(ge=0, le=20)] = 5,
    ) -> FaultDetailResult:
        """Get diagnosis, facts, inferences, limitations and evidence for one fault record."""
        try:
            result = catalog.get_fault_detail(fault_id, include, history_limit)
            return result.model_copy(
                update={"guidance": guidance_engine.for_tool("get_fault_detail", result)}
            )
        except KeyError as exc:
            raise ToolError(f"Fault record does not exist: {fault_id}") from exc

    @server.tool(
        title="查询历史故障",
        description="查询已关闭的验证、驳回和未定历史；只用于调查优先级，必须回到本次证据验证。",
        annotations=read_only,
    )
    def list_fault_history(
        asset_id: str | None = None,
        site_id: str | None = None,
        line_id: str | None = None,
        asset_type: str | None = None,
        fault_mode: str | None = None,
        diagnosis_status: list[DiagnosisStatus] | None = None,
        closed_from: datetime | None = None,
        closed_to: datetime | None = None,
        related_to_fault_id: str | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> FaultHistoryResult:
        """List closed history, preserving validated, rejected and inconclusive outcomes."""
        try:
            result = catalog.list_fault_history(
                asset_id=asset_id,
                site_id=site_id,
                line_id=line_id,
                asset_type=asset_type,
                fault_mode=fault_mode,
                diagnosis_status=diagnosis_status,
                closed_from=closed_from,
                closed_to=closed_to,
                related_to_fault_id=related_to_fault_id,
                cursor=cursor,
                limit=limit,
            )
            return result.model_copy(
                update={"guidance": guidance_engine.for_tool("list_fault_history", result)}
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        title="读取监测摘要",
        description="读取趋势、特征和数据质量；质量冲突时先检查传感链，质量有效时继续核对报警工况。",
        annotations=read_only,
    )
    def get_monitoring_summary(fault_id: str) -> MonitoringSummaryResult:
        """Get structured recent monitoring trends and data-quality status for a fault."""
        try:
            result = catalog.get_monitoring_summary(fault_id)
            return result.model_copy(
                update={
                    "guidance": guidance_engine.for_tool(
                        "get_monitoring_summary", result, fault=catalog.current_fault(fault_id)
                    )
                }
            )
        except KeyError as exc:
            raise ToolError(f"Investigation data does not exist: {fault_id}") from exc

    @server.tool(
        title="读取运行工况",
        description="读取负荷、转速、产量、配方及新鲜度；只追问真正阻塞可比性判断的缺失字段。",
        annotations=read_only,
    )
    def get_operating_context(fault_id: str) -> OperatingContextResult:
        """Get load, speed, production and freshness context without inferring missing values."""
        try:
            result = catalog.get_operating_context(fault_id)
            return result.model_copy(
                update={
                    "guidance": guidance_engine.for_tool(
                        "get_operating_context", result, fault=catalog.current_fault(fault_id)
                    )
                }
            )
        except KeyError as exc:
            raise ToolError(f"Investigation data does not exist: {fault_id}") from exc

    @server.tool(
        title="读取维修历史",
        description="读取维修记录及证据质量；维修时间关联不等于因果，下一步应核对维修前后可比趋势。",
        annotations=read_only,
    )
    def get_maintenance_history(fault_id: str) -> MaintenanceHistoryResult:
        """Get structured maintenance records and their evidence quality for a current fault."""
        try:
            result = catalog.get_maintenance_history(fault_id)
            return result.model_copy(
                update={
                    "guidance": guidance_engine.for_tool(
                        "get_maintenance_history", result, fault=catalog.current_fault(fault_id)
                    )
                }
            )
        except KeyError as exc:
            raise ToolError(f"Investigation data does not exist: {fault_id}") from exc

    @server.tool(
        title="比较同类设备",
        description="比较本机与同线同型设备并披露可比性限制；只能提高调查优先级，不能替代本机现场证据。",
        annotations=read_only,
    )
    def compare_peer_assets(fault_id: str) -> PeerComparisonResult:
        """Compare a faulted asset with selected peers and disclose comparability limits."""
        try:
            result = catalog.compare_peer_assets(fault_id)
            return result.model_copy(
                update={
                    "guidance": guidance_engine.for_tool(
                        "compare_peer_assets", result, fault=catalog.current_fault(fault_id)
                    )
                }
            )
        except KeyError as exc:
            raise ToolError(f"Investigation data does not exist: {fault_id}") from exc

    @server.tool(
        title="申请现场补测",
        description=(
            "在用户明确同意后创建或复用模拟现场补测请求；随后由现场人员采集并调用 "
            "ingest_field_measurement_result。"
        ),
        annotations=write_idempotent,
    )
    def request_field_measurement(
        ctx: Context,
        evaluation_session_id: str,
        task_id: str,
        consent: Literal[True],
    ) -> FieldMeasurementRequestResult:
        """Create one simulated field-measurement request after explicit user consent."""
        client_id = _authenticated_client_id(ctx, authenticator)
        evaluation, task, alarm = repository.get_task_snapshot(evaluation_session_id, task_id)
        if evaluation is None or task is None or alarm is None:
            raise ToolError("Task or evaluation session does not exist.")
        if evaluation.client_id != client_id or task.evaluation_session_id != evaluation.id:
            raise ToolError("Task access is forbidden.")
        record, created = repository.get_or_create_field_measurement_request(
            evaluation_session_id=evaluation.id,
            task_id=task.id,
            asset_id=task.asset_id,
            measurement_point_id=alarm.measurement_point_id,
        )
        result = FieldMeasurementRequestResult(
            request_id=record.id,
            evaluation_session_id=evaluation.id,
            task_id=task.id,
            asset_id=record.asset_id,
            measurement_point_id=record.measurement_point_id,
            status=record.status,
            created=created,
            is_simulated=True,
        )
        return result.model_copy(
            update={"guidance": guidance_engine.for_tool("request_field_measurement", result)}
        )

    @server.tool(
        title="接收模拟报警",
        description=(
            "幂等接收一条模拟报警并建立会话内任务；创建后读取 get_task 或使用 "
            "agent_invoke 开始调查。"
        ),
        annotations=write_idempotent,
    )
    def ingest_alarm(
        ctx: Context,
        event_id: str,
        evaluation_session_id: str,
        alarm_id: str,
        asset_id: str,
        measurement_point_id: str,
        severity: Literal["INFO", "WARNING", "CRITICAL"],
        diagnosis_text: str,
        confidence: Annotated[float, Field(ge=0, le=1)],
        algorithm_version: str,
        evidence_features: list[dict[str, Any]] | None = None,
        source_system: str = "PREDICTIVE_MAINTENANCE_SIMULATOR",
    ) -> dict[str, Any]:
        """Ingest a new simulated alarm and create an isolated task in an evaluation session."""
        request_id, trace_id = _request_ids()
        client_id = _authenticated_client_id(ctx, authenticator)
        try:
            result = event_service.ingest_alarm(
                request=AlarmRaisedEventRequest(
                    event_id=event_id,
                    event_type="ALARM_RAISED",
                    source_system=source_system,
                    occurred_at=datetime.now().astimezone(),
                    evaluation_session_id=evaluation_session_id,
                    payload=AlarmRaisedPayload(
                        alarm_id=alarm_id,
                        asset_id=asset_id,
                        measurement_point_id=measurement_point_id,
                        severity=severity,
                        diagnosis_text=diagnosis_text,
                        confidence=confidence,
                        algorithm_version=algorithm_version,
                        evidence_features=evidence_features or [],
                    ),
                ),
                client_id=client_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        payload = result.model_dump(mode="json")
        payload["guidance"] = guidance_engine.for_tool("ingest_alarm", payload).model_dump(
            mode="json"
        )
        return payload

    @server.tool(
        title="回传现场补测结果",
        description=(
            "幂等回传结构化现场补测结果；PASS 进入人工工程判断，PARTIAL/FAIL 必须补齐或重测。"
        ),
        annotations=write_idempotent,
    )
    def ingest_field_measurement_result(
        ctx: Context,
        event_id: str,
        evaluation_session_id: str,
        task_id: str,
        asset_id: str,
        measurement_point_id: str,
        collection_quality: Literal["PASS", "FAIL", "PARTIAL"],
        sound_analysis: dict[str, Any],
        vibration_analysis: dict[str, Any],
        operating_condition: str | None = None,
        source_system: str = "PORTABLE_ANALYSIS_SIMULATOR",
    ) -> dict[str, Any]:
        """Ingest a simulated structured portable-analysis result; raw waveforms are excluded."""
        request_id, trace_id = _request_ids()
        client_id = _authenticated_client_id(ctx, authenticator)
        try:
            result = event_service.ingest_field_measurement(
                request=FieldMeasurementCompletedEventRequest(
                    event_id=event_id,
                    event_type="FIELD_MEASUREMENT_COMPLETED",
                    source_system=source_system,
                    occurred_at=datetime.now().astimezone(),
                    evaluation_session_id=evaluation_session_id,
                    task_id=task_id,
                    payload=FieldMeasurementCompletedPayload(
                        asset_id=asset_id,
                        measurement_point_id=measurement_point_id,
                        collection_quality=collection_quality,
                        operating_condition=operating_condition,
                        sound_analysis=sound_analysis,
                        vibration_analysis=vibration_analysis,
                    ),
                ),
                client_id=client_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        payload = result.model_dump(mode="json")
        payload["guidance"] = guidance_engine.for_tool(
            "ingest_field_measurement_result",
            payload,
            collection_quality=collection_quality,
        ).model_dump(mode="json")
        return payload

    @server.tool(
        title="生成工单草稿",
        description="仅在现场证据质量门控通过后生成或复用模拟工单草稿；成功后必须由授权人处理一次性审批。",
        annotations=write_idempotent,
    )
    def draft_work_order(
        ctx: Context,
        evaluation_session_id: str,
        conversation_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        """Draft a simulated work order only after quality-gated field evidence."""
        request_id, trace_id = _request_ids()
        client_id = _authenticated_client_id(ctx, authenticator)
        try:
            result = agent_facade.invoke(
                request=AgentInvokeRequest(
                    evaluation_session_id=evaluation_session_id,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    message="生成工单草稿",
                ),
                client_id=client_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        payload = result.model_dump(mode="json")
        payload["guidance"] = guidance_engine.for_tool("draft_work_order", payload).model_dump(
            mode="json"
        )
        return payload

    @server.tool(
        title="决定工单审批",
        description="使用绑定证据版本的一次性 Challenge 明确批准或拒绝模拟工单；该调用不可重放。",
        annotations=write_once,
    )
    def decide_work_order_approval(
        ctx: Context,
        task_id: str,
        approval_id: str,
        approval_challenge: str,
        decision: Literal["APPROVE", "REJECT"],
        evidence_version: Annotated[int, Field(ge=1)],
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Apply a one-time explicit approval decision to a simulated work order."""
        request_id, trace_id = _request_ids()
        client_id = _authenticated_client_id(ctx, authenticator)
        try:
            result = approval_service.decide(
                task_id=task_id,
                request=ApprovalDecisionRequest(
                    approval_id=approval_id,
                    approval_challenge=approval_challenge,
                    decision=decision,
                    evidence_version=evidence_version,
                    comment=comment,
                ),
                client_id=client_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        payload = result.model_dump(mode="json")
        payload["guidance"] = guidance_engine.for_tool(
            "decide_work_order_approval", payload, decision=decision
        ).model_dump(mode="json")
        return payload

    @server.tool(
        title="回传工单完成",
        description="幂等回传模拟维修实际发现、动作和维修后诊断；随后复核改善、证据不足或需重开调查。",
        annotations=write_idempotent,
    )
    def ingest_work_order_completion(
        ctx: Context,
        event_id: str,
        evaluation_session_id: str,
        task_id: str,
        work_order_id: str,
        actual_fault: str,
        inspection_findings: str,
        actions_taken: list[str],
        post_maintenance_diagnosis: dict[str, Any],
        parts_replaced: list[str] | None = None,
        source_system: str = "EAM_SIMULATOR",
    ) -> dict[str, Any]:
        """Ingest simulated maintenance completion and validate the post-maintenance result."""
        request_id, trace_id = _request_ids()
        client_id = _authenticated_client_id(ctx, authenticator)
        now = datetime.now().astimezone()
        try:
            result = event_service.ingest_work_order_completion(
                request=WorkOrderCompletedEventRequest(
                    event_id=event_id,
                    event_type="WORK_ORDER_COMPLETED",
                    source_system=source_system,
                    occurred_at=now,
                    evaluation_session_id=evaluation_session_id,
                    task_id=task_id,
                    payload=WorkOrderCompletedPayload(
                        work_order_id=work_order_id,
                        actual_fault=actual_fault,
                        inspection_findings=inspection_findings,
                        actions_taken=actions_taken,
                        parts_replaced=parts_replaced or [],
                        completed_at=now,
                        post_maintenance_diagnosis=post_maintenance_diagnosis,
                    ),
                ),
                client_id=client_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        payload = result.model_dump(mode="json")
        payload["guidance"] = guidance_engine.for_tool(
            "ingest_work_order_completion", payload
        ).model_dump(mode="json")
        return payload

    @server.tool(
        title="自然语言调查编排",
        description="在一个隔离任务中用自然语言调查、补齐证据并获得按责任人排序的行动方案；会记录会话，写动作仍受同意和审批门控。",
        annotations=write_once,
    )
    def agent_invoke(
        ctx: Context,
        evaluation_session_id: str,
        conversation_id: str,
        task_id: str,
        message: Annotated[str, Field(min_length=1, max_length=8000)],
        locale: str = "zh-CN",
    ) -> MCPAgentInvokeResult:
        """Invoke the same Agent behavior exposed by the REST API."""
        request_id, trace_id = _request_ids()
        client_id = _authenticated_client_id(ctx, authenticator)
        try:
            result = agent_facade.invoke(
                request=AgentInvokeRequest(
                    evaluation_session_id=evaluation_session_id,
                    conversation_id=conversation_id,
                    task_id=task_id,
                    message=message,
                    locale=locale,
                ),
                client_id=client_id,
                request_id=request_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            raise ToolError(str(exc)) from exc
        response = result.model_dump(mode="json")
        _, task, _ = repository.get_task_snapshot(evaluation_session_id, task_id)
        fault = catalog.current_fault_for_asset(task.asset_id) if task is not None else None
        wrapped = MCPAgentInvokeResult(response=response)
        return wrapped.model_copy(
            update={
                "guidance": guidance_engine.for_tool(
                    "agent_invoke",
                    wrapped,
                    fault=fault,
                    task_state=result.data.task_state.value,
                )
            }
        )

    @server.tool(
        title="读取任务状态",
        description="读取会话内任务、证据、待审批和维修验证快照；按任务状态返回唯一明确的下一步。",
        annotations=read_only,
    )
    def get_task(ctx: Context, evaluation_session_id: str, task_id: str) -> TaskResult:
        """Read the persisted task and initial alarm for the current evaluation session."""
        client_id = _authenticated_client_id(ctx, authenticator)
        evaluation, task, alarm = repository.get_task_snapshot(evaluation_session_id, task_id)
        if evaluation is None or task is None or alarm is None:
            raise ToolError("Task or evaluation session does not exist.")
        if evaluation.client_id != client_id or task.evaluation_session_id != evaluation.id:
            raise ToolError("Task access is forbidden.")
        turns = repository.list_conversation_turns(task_id)
        claims = repository.list_human_claims(task_id)
        field_request = repository.get_field_measurement_request(task_id)
        field_measurements = repository.list_field_measurement_events(task_id)
        snapshot = task_service.get_snapshot(
            task_id=task_id,
            client_id=client_id,
            request_id="mcp_snapshot",
            trace_id="mcp_snapshot_trace",
        ).data
        result = TaskResult(
            task_id=task.id,
            evaluation_session_id=evaluation.id,
            task_state=task.state,
            asset_id=task.asset_id,
            alarm={
                "alarm_id": alarm.alarm_id,
                "severity": alarm.severity,
                "diagnosis_text": alarm.diagnosis_text,
                "confidence": alarm.confidence,
                "source_system": alarm.source_system,
                "observed_at": alarm.observed_at,
            },
            conversation_turns=[
                {
                    "turn_id": turn.id,
                    "message": turn.message,
                    "intent": turn.intent,
                    "answer": turn.answer,
                    "tool_names": json.loads(turn.tool_names_json),
                    "created_at": turn.created_at,
                }
                for turn in turns
            ],
            human_claims=[
                {
                    "evidence_id": claim.evidence_id,
                    "text": claim.claim_text,
                    "source_role": claim.source_role,
                    "quality_status": claim.quality_status,
                    "observed_at": claim.observed_at,
                }
                for claim in claims
            ],
            field_measurement_request=(
                {
                    "request_id": field_request.id,
                    "asset_id": field_request.asset_id,
                    "measurement_point_id": field_request.measurement_point_id,
                    "status": field_request.status,
                    "created_at": field_request.created_at,
                }
                if field_request is not None
                else None
            ),
            field_measurements=[
                {
                    "event_id": item.event_id,
                    "evidence_id": item.evidence_id,
                    "collection_quality": item.collection_quality,
                    "source_system": item.source_system,
                    "occurred_at": item.occurred_at,
                    "payload": json.loads(item.payload_json),
                }
                for item in field_measurements
            ],
            evidence_version=task.evidence_version,
            pending_approval=snapshot.pending_approval.model_dump(mode="json")
            if snapshot.pending_approval
            else None,
            work_order=snapshot.work_order.model_dump(mode="json") if snapshot.work_order else None,
            maintenance_validation=snapshot.maintenance_validation.model_dump(mode="json")
            if snapshot.maintenance_validation
            else None,
            timeline=[item.model_dump(mode="json") for item in snapshot.timeline],
            is_simulated=alarm.is_simulated,
        )
        return result.model_copy(
            update={"guidance": guidance_engine.for_tool("get_task", result, task_state=task.state)}
        )

    return server
