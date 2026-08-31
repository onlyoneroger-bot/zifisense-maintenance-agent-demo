from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from time import perf_counter
from typing import Any

from zifisense_agent_api.adapters.asset_fault_catalog import AssetFaultCatalog
from zifisense_agent_api.adapters.llm.base import (
    LLMBudgetExceededError,
    LLMProvider,
    LLMProviderError,
)
from zifisense_agent_api.application.guidance_engine import GuidanceEngine
from zifisense_agent_api.domain.errors import ApplicationError
from zifisense_agent_api.domain.llm_models import LLMAnswerRequest, LLMEvidence
from zifisense_agent_api.domain.task_state import TaskState
from zifisense_agent_api.infrastructure.repositories import EvaluationRepository
from zifisense_agent_api.transport.schemas import (
    AgentInference,
    AgentInvokeRequest,
    AgentInvokeResponse,
    AgentResponseData,
    Citation,
    EvidenceItem,
    Fact,
    OpenQuestion,
    PendingApproval,
    RecommendedAction,
    ResponseMeta,
    SystemDiagnosis,
    ToolExecution,
)


class InvestigationIntent(StrEnum):
    OVERVIEW = "OVERVIEW"
    MONITORING = "MONITORING"
    OPERATING_CONTEXT = "OPERATING_CONTEXT"
    MAINTENANCE = "MAINTENANCE"
    PEER_COMPARISON = "PEER_COMPARISON"
    HISTORY = "HISTORY"
    HUMAN_CONTEXT = "HUMAN_CONTEXT"
    FIELD_MEASUREMENT_CONSENT = "FIELD_MEASUREMENT_CONSENT"
    WORK_ORDER_DRAFT = "WORK_ORDER_DRAFT"
    SAFETY_DECISION = "SAFETY_DECISION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class AgentFacade:
    def __init__(
        self,
        repository: EvaluationRepository,
        catalog: AssetFaultCatalog,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._llm_provider = llm_provider
        self._guidance = GuidanceEngine()

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

        intent = self._route_intent(request.message)
        fault = self._catalog.current_fault_for_asset(task.asset_id)
        if fault is None:
            raise ApplicationError(
                404, "RESOURCE_NOT_FOUND", "No current fault is linked to the task asset."
            )

        tool_executions: list[ToolExecution] = []
        loaded: dict[str, Any] = {}

        def run_tool(name: str, source: str, operation):
            started = perf_counter()
            result = operation()
            elapsed_ms = max(0, round((perf_counter() - started) * 1000))
            tool_executions.append(
                ToolExecution(
                    tool_name=name,
                    status="SUCCEEDED",
                    source_system=source,
                    elapsed_ms=elapsed_ms,
                    is_simulated=True,
                )
            )
            return result

        fault_id = fault["fault_id"]
        if intent in {
            InvestigationIntent.OVERVIEW,
            InvestigationIntent.MONITORING,
            InvestigationIntent.OPERATING_CONTEXT,
            InvestigationIntent.MAINTENANCE,
            InvestigationIntent.PEER_COMPARISON,
            InvestigationIntent.HISTORY,
            InvestigationIntent.HUMAN_CONTEXT,
            InvestigationIntent.FIELD_MEASUREMENT_CONSENT,
            InvestigationIntent.WORK_ORDER_DRAFT,
            InvestigationIntent.SAFETY_DECISION,
        }:
            loaded["monitoring"] = run_tool(
                "get_monitoring_summary",
                "PREDICTIVE_MAINTENANCE_SIMULATOR",
                lambda: self._catalog.get_monitoring_summary(fault_id),
            )

        if intent in {
            InvestigationIntent.OVERVIEW,
            InvestigationIntent.MONITORING,
            InvestigationIntent.OPERATING_CONTEXT,
            InvestigationIntent.HUMAN_CONTEXT,
            InvestigationIntent.SAFETY_DECISION,
        }:
            loaded["operating_context"] = run_tool(
                "get_operating_context",
                "MES_SIMULATOR",
                lambda: self._catalog.get_operating_context(fault_id),
            )

        if intent in {InvestigationIntent.OVERVIEW, InvestigationIntent.MAINTENANCE}:
            loaded["maintenance"] = run_tool(
                "get_maintenance_history",
                "EAM_SIMULATOR",
                lambda: self._catalog.get_maintenance_history(fault_id),
            )

        if intent in {InvestigationIntent.OVERVIEW, InvestigationIntent.PEER_COMPARISON}:
            loaded["peers"] = run_tool(
                "compare_peer_assets",
                "PREDICTIVE_MAINTENANCE_SIMULATOR",
                lambda: self._catalog.compare_peer_assets(fault_id),
            )

        if intent is InvestigationIntent.HISTORY:
            loaded["history"] = run_tool(
                "list_fault_history",
                "EAM_SIMULATOR",
                lambda: self._catalog.list_fault_history(
                    asset_id=task.asset_id,
                    related_to_fault_id=fault_id,
                    limit=5,
                ),
            )

        field_events = (
            self._repository.list_field_measurement_events(task.id)
            if intent is not InvestigationIntent.OUT_OF_SCOPE
            else []
        )
        if field_events:
            loaded["field_measurements"] = field_events
            tool_executions.append(
                ToolExecution(
                    tool_name="read_field_measurement_results",
                    status="SUCCEEDED",
                    source_system="PORTABLE_ANALYSIS_SIMULATOR",
                    elapsed_ms=0,
                    is_simulated=True,
                )
            )

        human_claim = None
        if intent is InvestigationIntent.HUMAN_CONTEXT:
            now = datetime.now().astimezone()
            human_claim, created = self._repository.add_human_claim(
                evaluation_session_id=evaluation.id,
                task_id=task.id,
                claim_text=request.message.strip(),
                observed_at=now.isoformat(),
            )
            tool_executions.append(
                ToolExecution(
                    tool_name="record_human_input",
                    status="SUCCEEDED" if created else "SKIPPED",
                    source_system="HUMAN_INPUT_GATE",
                    elapsed_ms=0,
                    is_simulated=True,
                )
            )

        field_request = None
        if intent is InvestigationIntent.FIELD_MEASUREMENT_CONSENT:
            field_request, created = self._repository.get_or_create_field_measurement_request(
                evaluation_session_id=evaluation.id,
                task_id=task.id,
                asset_id=task.asset_id,
                measurement_point_id=alarm.measurement_point_id,
            )
            tool_executions.append(
                ToolExecution(
                    tool_name="request_field_measurement",
                    status="SUCCEEDED" if created else "SKIPPED",
                    source_system="FIELD_SERVICE_SIMULATOR",
                    elapsed_ms=0,
                    is_simulated=True,
                )
            )

        work_order_approval = None
        if intent is InvestigationIntent.WORK_ORDER_DRAFT:
            passed_field_event = next(
                (item for item in reversed(field_events) if item.collection_quality == "PASS"),
                None,
            )
            if passed_field_event is not None:
                work_order, approval, created = self._repository.get_or_create_work_order_approval(
                    evaluation_session_id=evaluation.id,
                    task_id=task.id,
                )
                if approval.status == "PENDING":
                    work_order_approval = (work_order, approval)
                else:
                    loaded["work_order_status"] = approval.status
                tool_executions.append(
                    ToolExecution(
                        tool_name="draft_work_order",
                        status="SUCCEEDED" if created else "SKIPPED",
                        source_system="EAM_SIMULATOR",
                        elapsed_ms=0,
                        is_simulated=True,
                    )
                )
            else:
                tool_executions.append(
                    ToolExecution(
                        tool_name="draft_work_order",
                        status="SKIPPED",
                        source_system="EVIDENCE_GATE",
                        elapsed_ms=0,
                        is_simulated=True,
                    )
                )
        existing_turns = self._repository.list_conversation_turns(task.id)
        next_state = self._next_state(TaskState(task.state), intent, len(existing_turns))
        if work_order_approval is not None:
            next_state = TaskState.APPROVAL_PENDING
        if next_state.value != task.state:
            self._repository.update_task_state(task.id, next_state.value)

        response_data = self._compose_response(
            intent=intent,
            task_state=next_state,
            fault=fault,
            alarm=alarm,
            loaded=loaded,
            tool_executions=tool_executions,
            human_claim=human_claim,
            field_request=field_request,
            work_order_approval=work_order_approval,
        )
        response_data, is_degraded = self._enhance_with_llm(
            request=request,
            request_id=request_id,
            intent=intent,
            response_data=response_data,
        )
        self._repository.append_conversation_turn(
            evaluation_session_id=evaluation.id,
            conversation_id=conversation.id,
            task_id=task.id,
            message=request.message,
            intent=intent.value,
            answer=response_data.answer,
            tool_names=[item.tool_name for item in tool_executions],
        )
        return AgentInvokeResponse(
            request_id=request_id,
            trace_id=trace_id,
            data=response_data,
            meta=ResponseMeta(
                timestamp=datetime.now().astimezone(),
                is_degraded=is_degraded,
            ),
        )

    def _enhance_with_llm(
        self,
        *,
        request: AgentInvokeRequest,
        request_id: str,
        intent: InvestigationIntent,
        response_data: AgentResponseData,
    ) -> tuple[AgentResponseData, bool]:
        safe_read_only_intents = {
            InvestigationIntent.OVERVIEW,
            InvestigationIntent.MONITORING,
            InvestigationIntent.OPERATING_CONTEXT,
            InvestigationIntent.MAINTENANCE,
            InvestigationIntent.PEER_COMPARISON,
            InvestigationIntent.HISTORY,
            InvestigationIntent.HUMAN_CONTEXT,
        }
        if self._llm_provider is None or intent not in safe_read_only_intents:
            return response_data, False

        provider_started = perf_counter()
        llm_request = LLMAnswerRequest(
            request_id=request_id,
            user_message=request.message,
            intent=intent.value,
            task_state=response_data.task_state.value,
            deterministic_answer=response_data.answer,
            diagnosis_text=response_data.system_diagnosis.diagnosis_text,
            diagnosis_confidence=response_data.system_diagnosis.confidence,
            evidence=[
                LLMEvidence(
                    evidence_id=item.evidence_id,
                    evidence_type=item.evidence_type,
                    summary=item.summary,
                    quality_status=item.quality_status,
                    usage_level=item.usage_level,
                )
                for item in response_data.evidence
            ],
        )
        try:
            enhancement = self._llm_provider.synthesize(llm_request)
        except LLMBudgetExceededError:
            skipped_execution = ToolExecution(
                tool_name="llm_answer_synthesis",
                status="SKIPPED",
                source_system="BUDGET_GATE",
                elapsed_ms=max(0, round((perf_counter() - provider_started) * 1000)),
                is_simulated=False,
            )
            return (
                response_data.model_copy(
                    update={
                        "tool_executions": [
                            *response_data.tool_executions,
                            skipped_execution,
                        ]
                    }
                ),
                True,
            )
        except LLMProviderError:
            failed_execution = ToolExecution(
                tool_name="llm_answer_synthesis",
                status="FAILED",
                source_system=(f"{self._llm_provider.provider.upper()}:{self._llm_provider.model}"),
                elapsed_ms=max(0, round((perf_counter() - provider_started) * 1000)),
                is_simulated=False,
            )
            return (
                response_data.model_copy(
                    update={
                        "tool_executions": [
                            *response_data.tool_executions,
                            failed_execution,
                        ]
                    }
                ),
                True,
            )

        evidence_by_id = {item.evidence_id: item for item in response_data.evidence}
        citations = [
            Citation(
                document_id=evidence_id,
                title=f"{evidence_by_id[evidence_id].evidence_type} 证据",
                locator=evidence_id,
                excerpt=evidence_by_id[evidence_id].summary,
            )
            for evidence_id in enhancement.cited_evidence_ids
        ]
        succeeded_execution = ToolExecution(
            tool_name="llm_answer_synthesis",
            status="SUCCEEDED",
            source_system=f"{enhancement.provider.upper()}:{enhancement.model}",
            elapsed_ms=enhancement.latency_ms,
            is_simulated=False,
        )
        enhanced_answer = enhancement.answer
        missing_actions = [
            action
            for action in response_data.recommended_actions
            if action.label not in enhanced_answer
        ]
        if missing_actions:
            ordered = "；".join(
                f"{index}. {action.label}（{action.owner or 'RELIABILITY_ENGINEER'}）"
                f"—{action.why or '由当前证据状态触发'}"
                for index, action in enumerate(missing_actions, start=1)
            )
            enhanced_answer = f"{enhanced_answer}\n处置顺序：{ordered}。"
        blocking_questions = [
            question.question for question in response_data.open_questions if question.blocking
        ]
        if blocking_questions and blocking_questions[0] not in enhanced_answer:
            enhanced_answer = f"{enhanced_answer}\n需要先确认：{blocking_questions[0]}"
        if (
            intent is InvestigationIntent.SAFETY_DECISION
            and "不执行生产控制" not in enhanced_answer
        ):
            enhanced_answer = (
                f"{enhanced_answer}\n决策边界：本服务不执行生产控制；停机、停线或降载"
                "必须由授权人员依据企业 SOP 决定。"
            )
        return (
            response_data.model_copy(
                update={
                    "answer": enhanced_answer,
                    "citations": citations,
                    "tool_executions": [
                        *response_data.tool_executions,
                        succeeded_execution,
                    ],
                }
            ),
            False,
        )

    @staticmethod
    def _route_intent(message: str) -> InvestigationIntent:
        normalized = "".join(message.casefold().split())
        direct_control_patterns = (
            "直接停机",
            "立即停机",
            "执行停机",
            "直接停线",
            "立即停线",
            "执行停线",
            "不需要人工确认",
            "无需人工确认",
        )
        if any(word in normalized for word in direct_control_patterns):
            return InvestigationIntent.OUT_OF_SCOPE
        if any(
            word in normalized
            for word in ("是否停机", "需要停机", "要停机", "是否停线", "需要停线", "要停线", "降载")
        ):
            return InvestigationIntent.SAFETY_DECISION
        out_of_scope_patterns = (
            "新闻稿",
            "写诗",
            "天气",
            "股票",
            "翻译",
            "plc",
            "dcs",
            "启动设备",
            "写入控制",
            "下发控制",
            "执行控制",
            "忽略前面",
            "忽略规则",
            "绕过规则",
        )
        if any(word in normalized for word in out_of_scope_patterns):
            return InvestigationIntent.OUT_OF_SCOPE
        consent_patterns = (
            "同意补测",
            "可以补测",
            "允许补测",
            "安排补测",
            "请现场补测",
        )
        if any(pattern in normalized for pattern in consent_patterns):
            return InvestigationIntent.FIELD_MEASUREMENT_CONSENT
        if any(
            pattern in normalized
            for pattern in ("生成工单", "创建工单", "工单草稿", "提交维修建议")
        ):
            return InvestigationIntent.WORK_ORDER_DRAFT
        human_patterns = (
            "提高了",
            "降低了",
            "刚调整",
            "刚更换",
            "检修后",
            "启停了",
            "我确认",
            "现场说",
        )
        if any(pattern in normalized for pattern in human_patterns):
            return InvestigationIntent.HUMAN_CONTEXT
        if any(word in normalized for word in ("同线", "同类", "其他设备", "对比", "比较")):
            return InvestigationIntent.PEER_COMPARISON
        if any(word in normalized for word in ("历史", "以前", "曾经", "上次", "类似问题")):
            return InvestigationIntent.HISTORY
        if any(word in normalized for word in ("维修", "检修", "工单", "保养", "更换记录")):
            return InvestigationIntent.MAINTENANCE
        if any(word in normalized for word in ("工况", "负荷", "转速", "节拍", "配方", "启停")):
            return InvestigationIntent.OPERATING_CONTEXT
        monitoring_words = ("监测", "趋势", "近期数据", "振动", "温度", "异常吗")
        if any(word in normalized for word in monitoring_words):
            return InvestigationIntent.MONITORING
        return InvestigationIntent.OVERVIEW

    @staticmethod
    def _next_state(
        current: TaskState, intent: InvestigationIntent, existing_turn_count: int
    ) -> TaskState:
        if intent is InvestigationIntent.OUT_OF_SCOPE:
            return current
        if intent is InvestigationIntent.HUMAN_CONTEXT:
            return TaskState.EVIDENCE_REVIEW
        if intent is InvestigationIntent.FIELD_MEASUREMENT_CONSENT:
            return TaskState.FIELD_EVIDENCE_PENDING
        if current is TaskState.ALARM_RECEIVED:
            return TaskState.CONTEXT_COLLECTING
        if current is TaskState.CONTEXT_COLLECTING and existing_turn_count >= 1:
            return TaskState.EVIDENCE_REVIEW
        return current

    def _compose_response(
        self,
        *,
        intent: InvestigationIntent,
        task_state: TaskState,
        fault: dict[str, Any],
        alarm,
        loaded: dict[str, Any],
        tool_executions: list[ToolExecution],
        human_claim,
        field_request,
        work_order_approval,
    ) -> AgentResponseData:
        observed_at = datetime.fromisoformat(alarm.observed_at)
        alarm_evidence_id = alarm.evidence_id
        facts = [
            Fact(
                text=f"资产 {alarm.asset_id} 在测点 {alarm.measurement_point_id} 收到报警。",
                source_system=alarm.source_system,
                observed_at=observed_at,
                evidence_id=alarm_evidence_id,
            )
        ]
        evidence = [
            EvidenceItem(
                evidence_id=alarm_evidence_id,
                evidence_type="ALARM",
                summary=alarm.evidence_summary,
                source_system=alarm.source_system,
                observed_at=observed_at,
                quality_status="VALID",
                usage_level="DECISION_REFERENCE",
                is_simulated=alarm.is_simulated,
                conflicts_with=[],
            )
        ]
        inferences: list[AgentInference] = []

        monitoring = loaded.get("monitoring")
        if monitoring is not None:
            facts.append(
                Fact(
                    text=monitoring.trend,
                    source_system=monitoring.source_system,
                    observed_at=monitoring.observed_at,
                    evidence_id=monitoring.evidence_id,
                )
            )
            evidence.append(
                EvidenceItem(
                    evidence_id=monitoring.evidence_id,
                    evidence_type="ALARM",
                    summary=monitoring.trend,
                    source_system=monitoring.source_system,
                    observed_at=monitoring.observed_at,
                    quality_status=(
                        "CONFLICTING" if monitoring.data_quality == "CONFLICTING" else "VALID"
                    ),
                    usage_level="DECISION_REFERENCE",
                    is_simulated=True,
                    conflicts_with=[],
                )
            )

        context = loaded.get("operating_context")
        if context is not None:
            context_summary = (
                f"最近已知工况：负荷 {context.load_percent}%、转速 {context.speed_rpm} rpm，"
                f"新鲜度 {context.freshness}。"
            )
            facts.append(
                Fact(
                    text=context_summary,
                    source_system=context.source_system,
                    observed_at=context.observed_at,
                    evidence_id=context.evidence_id,
                )
            )
            evidence.append(
                EvidenceItem(
                    evidence_id=context.evidence_id,
                    evidence_type="OPERATING_CONTEXT",
                    summary=context_summary,
                    source_system=context.source_system,
                    observed_at=context.observed_at,
                    quality_status=("STALE" if context.freshness == "STALE" else "VALID"),
                    usage_level="QUERY_GUIDANCE",
                    is_simulated=True,
                    conflicts_with=[],
                )
            )

        maintenance = loaded.get("maintenance")
        if maintenance is not None:
            for record in maintenance.records:
                record_time = datetime.fromisoformat(record["completed_at"])
                facts.append(
                    Fact(
                        text=f"维修记录：{record['summary']}",
                        source_system=record["source_system"],
                        observed_at=record_time,
                        evidence_id=maintenance.evidence_id,
                    )
                )
            evidence.append(
                EvidenceItem(
                    evidence_id=maintenance.evidence_id,
                    evidence_type="MAINTENANCE_HISTORY",
                    summary=f"取得 {len(maintenance.records)} 条维修记录。",
                    source_system=maintenance.source_system,
                    observed_at=(
                        datetime.fromisoformat(maintenance.records[0]["completed_at"])
                        if maintenance.records
                        else observed_at
                    ),
                    quality_status="VALID",
                    usage_level="QUERY_GUIDANCE",
                    is_simulated=True,
                    conflicts_with=[],
                )
            )

        peers = loaded.get("peers")
        if peers is not None:
            evidence.append(
                EvidenceItem(
                    evidence_id=peers.evidence_id,
                    evidence_type="OPERATING_CONTEXT",
                    summary=peers.analysis,
                    source_system=peers.source_system,
                    observed_at=peers.observed_at,
                    quality_status="VALID" if peers.comparability == "GOOD" else "INCOMPLETE",
                    usage_level="QUERY_GUIDANCE",
                    is_simulated=True,
                    conflicts_with=[],
                )
            )
            inferences.append(
                AgentInference(
                    text=peers.analysis,
                    supporting_evidence_ids=[peers.evidence_id],
                )
            )

        history = loaded.get("history")
        if history is not None:
            for item in history.items:
                summary = (
                    f"历史记录 {item.fault_id} 的结局为 {item.diagnosis_status}，"
                    f"相似点包括 {', '.join(item.similarity.matched_dimensions)}，"
                    f"差异包括 {', '.join(item.similarity.differences)}。"
                )
                evidence_id = f"EVD-HISTORY-{item.fault_id}"
                evidence.append(
                    EvidenceItem(
                        evidence_id=evidence_id,
                        evidence_type="MAINTENANCE_HISTORY",
                        summary=summary,
                        source_system="EAM_SIMULATOR",
                        observed_at=item.closed_at,
                        quality_status="VALID",
                        usage_level="QUERY_GUIDANCE",
                        is_simulated=True,
                        conflicts_with=[],
                    )
                )
            if history.items:
                inferences.append(
                    AgentInference(
                        text="历史案例可用于安排调查优先级，但不能替代本次工况和现场证据。",
                        supporting_evidence_ids=[
                            f"EVD-HISTORY-{item.fault_id}" for item in history.items
                        ],
                    )
                )

        if human_claim is not None:
            human_observed_at = datetime.fromisoformat(human_claim.observed_at)
            evidence.append(
                EvidenceItem(
                    evidence_id=human_claim.evidence_id,
                    evidence_type="HUMAN_CLAIM",
                    summary=human_claim.claim_text,
                    source_system=human_claim.source_role,
                    observed_at=human_observed_at,
                    quality_status="UNVERIFIED",
                    usage_level="RECORD_ONLY",
                    is_simulated=True,
                    conflicts_with=[],
                )
            )

        field_measurements = loaded.get("field_measurements", [])
        for field_measurement in field_measurements:
            payload = json.loads(field_measurement.payload_json)
            quality_map = {
                "PASS": "VALID",
                "PARTIAL": "INCOMPLETE",
                "FAIL": "REJECTED",
            }
            summary = (
                f"现场补测质量 {field_measurement.collection_quality}；"
                f"声学：{payload['sound_analysis'].get('summary', '无摘要')}；"
                f"振动：{payload['vibration_analysis'].get('summary', '无摘要')}。"
            )
            evidence.append(
                EvidenceItem(
                    evidence_id=field_measurement.evidence_id,
                    evidence_type="PORTABLE_MEASUREMENT",
                    summary=summary,
                    source_system=field_measurement.source_system,
                    observed_at=datetime.fromisoformat(field_measurement.occurred_at),
                    quality_status=quality_map[field_measurement.collection_quality],
                    usage_level=(
                        "DECISION_REFERENCE"
                        if field_measurement.collection_quality == "PASS"
                        else "RECORD_ONLY"
                    ),
                    is_simulated=True,
                    conflicts_with=[],
                )
            )
            if field_measurement.collection_quality == "PASS":
                inferences.append(
                    AgentInference(
                        text="质量合格的便携补测支持进入人工工程判断，但仍不是自动最终结论。",
                        supporting_evidence_ids=[field_measurement.evidence_id],
                    )
                )

        if monitoring is not None and maintenance is not None and maintenance.records:
            inferences.append(
                AgentInference(
                    text="当前监测特征与既往维修记录存在调查关联，但尚不足以确认同一故障。",
                    supporting_evidence_ids=[monitoring.evidence_id, maintenance.evidence_id],
                )
            )

        recommended_steps = self._guidance.agent_actions(
            fault=fault,
            loaded=loaded,
            intent=intent.value,
            task_state=task_state.value,
            field_request=field_request,
            work_order_approval=work_order_approval,
        )
        answer = self._answer_for(
            intent,
            fault,
            loaded,
            human_claim,
            field_request,
            work_order_approval,
        )
        if recommended_steps:
            ordered_actions = "；".join(
                f"{index}. {step.title}（{step.owner}）"
                for index, step in enumerate(recommended_steps, start=1)
            )
            answer = f"{answer}\n处置顺序：{ordered_actions}。"
        open_questions = self._open_questions(loaded, human_claim)
        return AgentResponseData(
            answer=answer,
            task_state=task_state,
            confirmed_facts=facts,
            system_diagnosis=SystemDiagnosis(
                diagnosis_text=alarm.diagnosis_text,
                confidence=alarm.confidence,
                source_system=alarm.source_system,
                algorithm_version=alarm.algorithm_version,
            ),
            agent_inferences=inferences,
            open_questions=open_questions,
            evidence=evidence,
            citations=[],
            tool_executions=tool_executions,
            recommended_actions=[
                RecommendedAction(
                    code=step.code,
                    label=step.title,
                    why=step.why,
                    owner=step.owner,
                    required_inputs=step.required_inputs,
                    requires_consent=step.requires_consent,
                    requires_approval=step.requires_approval,
                    blocking=step.blocking,
                    next_tool=step.next_tool,
                )
                for step in recommended_steps
            ],
            pending_approval=(
                PendingApproval(
                    approval_id=work_order_approval[1].id,
                    approval_challenge=work_order_approval[1].approval_challenge,
                    approval_type="SUBMIT_WORK_ORDER",
                    evidence_version=work_order_approval[1].evidence_version,
                    expires_at=datetime.fromisoformat(work_order_approval[1].expires_at),
                    impact_preview={
                        "work_order_id": work_order_approval[0].id,
                        "target": "SIMULATED_EAM",
                        "production_write": False,
                    },
                )
                if work_order_approval is not None
                else None
            ),
        )

    @staticmethod
    def _answer_for(
        intent: InvestigationIntent,
        fault: dict[str, Any],
        loaded: dict[str, Any],
        human_claim,
        field_request,
        work_order_approval,
    ) -> str:
        prefix = (
            f"当前模拟调查记录 {fault['fault_id']} 的专业候选诊断是“"
            f"{fault['primary_diagnosis']}”（来源 {fault['diagnosis_source']}，"
            f"置信度 {fault['diagnosis_confidence']:.2f}）。"
        )
        if intent is InvestigationIntent.OUT_OF_SCOPE:
            return (
                "该问题不属于设备智能运维范围。我可以查询设备列表、当前故障、监测趋势、"
                "近期工况、维修历史、同类设备对比和历史故障。"
            )
        if intent is InvestigationIntent.SAFETY_DECISION:
            severity = fault.get("severity", "INFO")
            diagnosis_status = fault.get("diagnosis_status", "CANDIDATE")
            if severity in {"CRITICAL", "MAJOR"}:
                return (
                    prefix + f"当前等级为 {severity}、诊断成熟度为 {diagnosis_status}。"
                    "是否停机不能由目录记录自动决定：请立即由值班工程师核实当前负荷、"
                    "保护/联锁状态和异常持续性，再由授权人员依据企业 SOP 决定停机、降载或继续运行。"
                    "本服务不具备也不会调用生产控制能力。"
                )
            return (
                prefix + f"当前等级为 {severity}、诊断成熟度为 {diagnosis_status}，"
                "现有证据不足以建议停机。"
                "应先在可比工况补齐趋势和现场证据；如达到企业既定安全或保护阈值，"
                "再由授权人员按 SOP 决策。本服务不执行生产控制。"
            )
        if intent is InvestigationIntent.WORK_ORDER_DRAFT:
            decided_status = loaded.get("work_order_status")
            if decided_status is not None:
                return (
                    prefix
                    + f"该模拟工单的审批已处于 {decided_status}，不会重新签发或恢复旧 Challenge。"
                )
            if work_order_approval is None:
                return prefix + "当前没有质量合格的现场补测证据，证据门控拒绝生成工单草稿。"
            return (
                prefix + f"已生成模拟工单草稿 {work_order_approval[0].id}，"
                "尚未提交；必须使用一次性审批 Challenge 明确批准。"
            )
        field_measurements = loaded.get("field_measurements", [])
        if field_measurements:
            latest = field_measurements[-1]
            if latest.collection_quality == "PASS":
                return (
                    prefix + "已收到质量合格的结构化现场补测结果，可作为人工工程判断的参考；"
                    "系统不会自动把它升级为最终故障结论。"
                )
            return (
                prefix + f"现场补测质量为 {latest.collection_quality}，当前证据不足，"
                "需要在可比工况下重新采集，不能升级工程结论。"
            )
        if intent is InvestigationIntent.HUMAN_CONTEXT and human_claim is not None:
            return (
                prefix
                + f"已原样记录你的描述“{human_claim.claim_text}”，但它目前是未验证的人工信息，"
                "不会覆盖专业报警。建议补齐发生时间、负荷和转速，并在可比工况下复核。"
            )
        if intent is InvestigationIntent.FIELD_MEASUREMENT_CONSENT and field_request is not None:
            return (
                prefix + f"已根据你的明确同意创建模拟现场补测请求 {field_request.id}，"
                f"测点为 {field_request.measurement_point_id}。结果回传前不会升级工程结论。"
            )
        if intent is InvestigationIntent.PEER_COMPARISON:
            return prefix + loaded["peers"].analysis + "该对比只用于调查，不直接改变诊断置信度。"
        if intent is InvestigationIntent.HISTORY:
            count = len(loaded["history"].items)
            return prefix + f"找到 {count} 条相关历史；其中的成功、否定和未定结局均被保留。"
        if intent is InvestigationIntent.MAINTENANCE:
            count = len(loaded["maintenance"].records)
            return prefix + f"查询到 {count} 条维修记录，详见证据列表。"
        if intent is InvestigationIntent.OPERATING_CONTEXT:
            context = loaded["operating_context"]
            return (
                prefix + f"最近已知负荷为 {context.load_percent}%、转速 {context.speed_rpm} rpm，"
                f"数据新鲜度为 {context.freshness}；仍需核实报警时工况。"
            )
        if intent is InvestigationIntent.MONITORING:
            return (
                prefix + loaded["monitoring"].trend + "；是否由设备本体引起仍需结合工况和现场证据。"
            )
        return (
            prefix
            + loaded["monitoring"].trend
            + "。工况记录尚不完整，历史与同类比较只支持确定调查方向，不能替代现场确认。"
        )

    @staticmethod
    def _open_questions(loaded: dict[str, Any], human_claim) -> list[OpenQuestion]:
        questions: list[OpenQuestion] = []
        context = loaded.get("operating_context")
        if context is not None and context.missing_fields:
            questions.append(
                OpenQuestion(
                    question="近期负荷、转速、节拍、配方或启停是否发生变化？",
                    reason=f"当前缺少：{', '.join(context.missing_fields)}。",
                    blocking=True,
                )
            )
        if human_claim is not None:
            questions.append(
                OpenQuestion(
                    question="这项变化发生的准确时间和当时负荷、转速是多少？",
                    reason="人工描述必须与报警时间和可比工况对齐后才能用于判断。",
                    blocking=True,
                )
            )
        questions.append(
            OpenQuestion(
                question="如果工况核对后仍异常，是否同意现场便携三轴振动补测？",
                reason="现场补测可区分设备异常、安装问题和数据质量问题。",
                blocking=False,
            )
        )
        return questions
