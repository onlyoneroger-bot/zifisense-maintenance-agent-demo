from __future__ import annotations

from datetime import datetime

from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.domain.task_state import TaskState
from zifisense_agent_api.infrastructure.repositories import EvaluationRepository
from zifisense_agent_api.transport.schemas import (
    AgentInvokeRequest,
    AgentInvokeResponse,
    AgentResponseData,
    EvidenceItem,
    Fact,
    OpenQuestion,
    ResponseMeta,
    SystemDiagnosis,
)


class AgentFacade:
    def __init__(self, repository: EvaluationRepository) -> None:
        self._repository = repository

    def invoke(
        self,
        *,
        request: AgentInvokeRequest,
        client_id: str,
        request_id: str,
        trace_id: str,
    ) -> AgentInvokeResponse:
        evaluation, conversation, task, alarm = self._repository.get_task_context(
            request.evaluation_session_id,
            request.conversation_id,
            request.task_id,
        )
        missing = []
        if evaluation is None:
            missing.append("evaluation_session_id")
        if conversation is None:
            missing.append("conversation_id")
        if task is None:
            missing.append("task_id")
        if missing:
            raise ApplicationError(
                404,
                "RESOURCE_NOT_FOUND",
                "One or more requested resources do not exist.",
                details={"missing": missing},
            )
        assert evaluation is not None and conversation is not None and task is not None
        if evaluation.client_id != client_id:
            raise ApplicationError(403, "INSUFFICIENT_SCOPE", "Session access is forbidden.")
        if conversation.evaluation_session_id != evaluation.id:
            raise ApplicationError(
                403, "INSUFFICIENT_SCOPE", "Conversation does not belong to this session."
            )
        if task.evaluation_session_id != evaluation.id:
            raise ApplicationError(
                403, "INSUFFICIENT_SCOPE", "Task does not belong to this session."
            )
        if alarm is None:
            raise ApplicationError(
                404, "RESOURCE_NOT_FOUND", "The task has no initial alarm evidence."
            )

        observed_at = datetime.fromisoformat(alarm.observed_at)
        answer = (
            f"当前任务记录到{alarm.severity}级模拟报警：{alarm.diagnosis_text}，"
            f"比赛 Fixture 中的专业诊断置信度为 {alarm.confidence:.2f}。"
            "当前 Sprint 仅验证受保护 API、独立会话和基于已持久化报警的降级响应；"
            "RAG、工业系统工具、事件接入、证据冲突和审批闭环尚未启用。"
        )
        evidence_id = alarm.evidence_id
        return AgentInvokeResponse(
            request_id=request_id,
            trace_id=trace_id,
            data=AgentResponseData(
                answer=answer,
                task_state=TaskState(task.state),
                confirmed_facts=[
                    Fact(
                        text=(
                            f"资产 {alarm.asset_id} 在测点 {alarm.measurement_point_id} 收到报警。"
                        ),
                        source_system=alarm.source_system,
                        observed_at=observed_at,
                        evidence_id=evidence_id,
                    )
                ],
                system_diagnosis=SystemDiagnosis(
                    diagnosis_text=alarm.diagnosis_text,
                    confidence=alarm.confidence,
                    source_system=alarm.source_system,
                    algorithm_version=alarm.algorithm_version,
                ),
                agent_inferences=[],
                open_questions=[
                    OpenQuestion(
                        question="是否继续进入工况、历史和知识检索阶段？",
                        reason="这些能力将在后续 Sprint 启用，当前没有足够证据形成处置建议。",
                        blocking=True,
                    )
                ],
                evidence=[
                    EvidenceItem(
                        evidence_id=evidence_id,
                        evidence_type="ALARM",
                        summary=alarm.evidence_summary,
                        source_system=alarm.source_system,
                        observed_at=observed_at,
                        quality_status="VALID",
                        usage_level="DECISION_REFERENCE",
                        is_simulated=alarm.is_simulated,
                        conflicts_with=[],
                    )
                ],
                citations=[],
                tool_executions=[],
                recommended_actions=[],
                pending_approval=None,
            ),
            meta=ResponseMeta(timestamp=datetime.now().astimezone(), is_degraded=True),
        )
