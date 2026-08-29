from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from zifisense_agent_api.infrastructure.auth import ClientIdentity
from zifisense_agent_api.transport.dependencies import get_request_ids, require_client
from zifisense_agent_api.transport.schemas import (
    AgentSummary,
    CapabilitiesData,
    CapabilitiesResponse,
    CapabilityItem,
    CreateEvaluationSessionRequest,
    CreateEvaluationSessionResponse,
    ResponseMeta,
    ScenarioSummary,
)

router = APIRouter(prefix="/api/v1", tags=["Evaluation"])


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    operation_id="getCapabilities",
)
def get_capabilities(
    request: Request,
    _identity: Annotated[ClientIdentity, Depends(require_client("capability:read"))],
) -> CapabilitiesResponse:
    fixture = request.app.state.fixtures.load_alarm_scenario("reducer_gear_alarm_v1")
    request_id, trace_id = get_request_ids(request)
    return CapabilitiesResponse(
        request_id=request_id,
        trace_id=trace_id,
        data=CapabilitiesData(
            agent=AgentSummary(
                name="zifisense-intelligent-maintenance-agent",
                version=request.app.state.settings.app_version,
                locale="zh-CN",
            ),
            scenarios=[
                ScenarioSummary(
                    scenario_id=fixture.scenario_id,
                    name=fixture.scenario_name,
                    description=fixture.scenario_description,
                    suggested_questions=list(fixture.suggested_questions),
                )
            ],
            capabilities=[
                CapabilityItem(
                    code="asset_catalog_query",
                    name="设备目录查询",
                    verification_hint="调用 MCP list_assets，可按产线、类型和活动故障筛选。",
                ),
                CapabilityItem(
                    code="current_fault_query",
                    name="当前故障查询",
                    verification_hint="调用 MCP list_current_faults 查询正在调查的记录。",
                ),
                CapabilityItem(
                    code="fault_detail_query",
                    name="故障详情与诊断分析",
                    verification_hint="调用 MCP get_fault_detail 检查事实、推断、证据和待补问题。",
                ),
                CapabilityItem(
                    code="fault_history_query",
                    name="历史故障检索",
                    verification_hint="调用 MCP list_fault_history 查询相似记录及其验证结局。",
                ),
                CapabilityItem(
                    code="monitoring_summary",
                    name="近期监测摘要",
                    verification_hint="在 Agent 中询问近期数据，或调用 get_monitoring_summary。",
                ),
                CapabilityItem(
                    code="operating_context_query",
                    name="工况查询与追问",
                    verification_hint="询问报警时负荷、转速或工况，检查缺失字段追问。",
                ),
                CapabilityItem(
                    code="maintenance_history_query",
                    name="维修记录查询",
                    verification_hint="询问近期检修记录，或调用 get_maintenance_history。",
                ),
                CapabilityItem(
                    code="peer_comparison",
                    name="同线设备对比",
                    verification_hint="询问同线其他设备是否异常，或调用 compare_peer_assets。",
                ),
                CapabilityItem(
                    code="context_orchestration",
                    name="受控多轮调查编排",
                    verification_hint="连续询问现象、工况和同线设备，使用 get_task 检查回放。",
                ),
                CapabilityItem(
                    code="human_input_gate",
                    name="人工信息证据门控",
                    verification_hint="提供近期工况变化，检查其被标记为 HUMAN_CLAIM/UNVERIFIED。",
                ),
                CapabilityItem(
                    code="portable_measurement_ingest",
                    name="现场补测协同与结果接入",
                    verification_hint=(
                        "明确同意补测后调用 request_field_measurement，再回传结构化补测结果。"
                    ),
                ),
                CapabilityItem(
                    code="audit_traceability",
                    name="会话与工具审计回放",
                    verification_hint="调用 get_task 检查对话轮次、意图、工具和人工声明。",
                ),
            ],
            supported_event_types=["FIELD_MEASUREMENT_COMPLETED"],
            safety_boundaries=[
                "All current catalog, fault, monitoring, context, maintenance, and "
                "peer-comparison data are explicitly simulated Fixture data.",
                "Alarm and work-order-completion event ingestion, plus approval-gated "
                "work-order writes, are not yet available.",
                "External industrial systems will be connected through explicitly "
                "simulated adapters.",
                "LLM does not diagnose raw high-frequency time-series data.",
                "Production-control actions are not exposed.",
                "Formal work-order submission requires explicit approval.",
            ],
        ),
        meta=ResponseMeta(timestamp=datetime.now().astimezone(), is_degraded=False),
    )


@router.post(
    "/evaluation/sessions",
    response_model=CreateEvaluationSessionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createEvaluationSession",
)
def create_evaluation_session(
    payload: CreateEvaluationSessionRequest,
    request: Request,
    identity: Annotated[ClientIdentity, Depends(require_client("evaluation:create"))],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> CreateEvaluationSessionResponse:
    request_id, trace_id = get_request_ids(request)
    return request.app.state.evaluation_service.create(
        request=payload,
        client_id=identity.client_id,
        idempotency_key=idempotency_key,
        request_id=request_id,
        trace_id=trace_id,
    )
