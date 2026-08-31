from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zifisense_agent_api.domain.guidance import GuidanceEnvelope, GuidanceStep

_SEVERITY_URGENCY = {
    "INFO": "ROUTINE",
    "WARNING": "PRIORITY",
    "MAJOR": "URGENT",
    "CRITICAL": "CRITICAL",
}


class GuidanceEngine:
    """Deterministic next-action policy shared by every MCP tool and the Agent."""

    _BASE_CONSTRAINTS = [
        "当前目录、任务和处置结果均为比赛模拟数据。",
        "候选诊断、历史关联和同类对比不能替代授权工程师的最终判断。",
        "本服务不暴露 PLC、DCS、启停或其他生产控制能力。",
    ]

    @staticmethod
    def _data(value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, Mapping):
            return dict(value)
        return {}

    @staticmethod
    def _step(
        code: str,
        title: str,
        why: str,
        owner: str,
        *,
        required_inputs: list[str] | None = None,
        consent: bool = False,
        approval: bool = False,
        blocking: bool = False,
        next_tool: str | None = None,
    ) -> GuidanceStep:
        return GuidanceStep(
            code=code,
            title=title,
            why=why,
            owner=owner,
            required_inputs=required_inputs or [],
            requires_consent=consent,
            requires_approval=approval,
            blocking=blocking,
            next_tool=next_tool,
        )

    def _envelope(
        self,
        *,
        profile: str,
        summary: str,
        urgency: str = "ROUTINE",
        stage: str,
        actionability: str,
        steps: list[GuidanceStep],
        questions: list[str] | None = None,
        escalation: list[str] | None = None,
    ) -> GuidanceEnvelope:
        return GuidanceEnvelope(
            profile=profile,
            summary=summary,
            urgency=urgency,
            current_stage=stage,
            actionability=actionability,
            next_steps=steps,
            blocking_questions=questions or [],
            escalation_conditions=escalation or [],
            constraints=list(self._BASE_CONSTRAINTS),
            recommended_next_tools=[step.next_tool for step in steps if step.next_tool],
        )

    def for_tool(
        self,
        tool_name: str,
        result: Any,
        *,
        fault: Mapping[str, Any] | None = None,
        task_state: str | None = None,
        collection_quality: str | None = None,
        decision: str | None = None,
    ) -> GuidanceEnvelope:
        data = self._data(result)
        if tool_name == "list_assets":
            return self._assets(data)
        if tool_name == "list_current_faults":
            return self._faults(data)
        if tool_name == "get_fault_detail":
            return self._fault_detail(data)
        if tool_name == "list_fault_history":
            return self._history(data)
        if tool_name in {
            "get_monitoring_summary",
            "get_operating_context",
            "get_maintenance_history",
            "compare_peer_assets",
        }:
            return self._evidence(tool_name, data, fault=fault)
        if tool_name == "request_field_measurement":
            return self._field_request(data)
        if tool_name == "ingest_field_measurement_result":
            return self._field_result(data, collection_quality=collection_quality)
        if tool_name in {"create_evaluation_session", "ingest_alarm"}:
            return self._intake(tool_name, data)
        if tool_name == "draft_work_order":
            return self._draft(data)
        if tool_name == "decide_work_order_approval":
            return self._approval(data, decision=decision)
        if tool_name == "ingest_work_order_completion":
            return self._completion(data)
        if tool_name == "get_task":
            return self._task(data, task_state=task_state)
        if tool_name == "agent_invoke":
            return self._agent(data, fault=fault, task_state=task_state)
        raise ValueError(f"Unsupported guidance tool: {tool_name}")

    def agent_actions(
        self,
        *,
        fault: Mapping[str, Any],
        loaded: Mapping[str, Any],
        intent: str,
        task_state: str,
        field_request: Any = None,
        work_order_approval: Any = None,
    ) -> list[GuidanceStep]:
        """Return the ordered actions used by both REST Agent and MCP guidance."""
        severity = fault.get("severity", "INFO")
        diagnosis_status = fault.get("diagnosis_status", "CANDIDATE")
        if intent == "SAFETY_DECISION":
            steps = [
                self._step(
                    "VERIFY_LIVE_SAFETY_CONTEXT",
                    "由值班工程师立即核实当前负荷、保护/联锁状态和异常是否持续",
                    "目录证据不是实时控制信号，先确认是否触发企业既定安全边界。",
                    "DUTY_ENGINEER",
                    required_inputs=["当前负荷", "保护/联锁状态", "异常持续性", "备用机可用性"],
                    blocking=True,
                )
            ]
            if severity in {"CRITICAL", "MAJOR"}:
                steps.append(
                    self._step(
                        "APPLY_ENTERPRISE_SOP",
                        "由授权人员依据企业 SOP 决定停机、降载或继续运行",
                        "本服务只提供证据化决策支持，不执行生产控制。",
                        "AUTHORIZED_APPROVER",
                        required_inputs=["企业处置阈值", "生产与人员影响", "现场复核结果"],
                        approval=True,
                        blocking=True,
                    )
                )
            else:
                steps.append(
                    self._step(
                        "CONTINUE_COMPARABLE_MONITORING",
                        "在可比工况下继续监测并补齐证据",
                        "当前严重度不足以在没有企业阈值和现场证据时建议停机。",
                        "RELIABILITY_ENGINEER",
                        next_tool="get_monitoring_summary",
                    )
                )
            return steps
        if intent == "WORK_ORDER_DRAFT":
            if work_order_approval is not None:
                return [
                    self._step(
                        "REVIEW_WORK_ORDER_APPROVAL",
                        "核对工单影响预览、证据版本并由授权人审批",
                        "工单草稿不会自动提交，一次性 Challenge 必须显式决定。",
                        "AUTHORIZED_APPROVER",
                        required_inputs=[
                            "impact_preview",
                            "approval_challenge",
                            "evidence_version",
                        ],
                        approval=True,
                        blocking=True,
                        next_tool="decide_work_order_approval",
                    )
                ]
            return [
                self._step(
                    "COMPLETE_FIELD_EVIDENCE",
                    "先取得质量 PASS 的现场补测并完成工程复核",
                    "当前证据门控不允许生成可审批工单。",
                    "RELIABILITY_ENGINEER",
                    consent=True,
                    blocking=True,
                    next_tool="request_field_measurement",
                )
            ]
        if field_request is not None:
            return [
                self._step(
                    "COLLECT_AND_RETURN_FIELD_RESULT",
                    "由现场人员在指定测点完成采集并回传结构化结果",
                    "结果返回且质量 PASS 前，不升级诊断或生成工单。",
                    "FIELD_TECHNICIAN",
                    required_inputs=["可比工况", "声学摘要", "振动摘要", "collection_quality"],
                    blocking=True,
                    next_tool="ingest_field_measurement_result",
                )
            ]
        field_measurements = list(loaded.get("field_measurements", []))
        if field_measurements:
            latest = field_measurements[-1]
            if getattr(latest, "collection_quality", None) == "PASS":
                return [
                    self._step(
                        "ENGINEERING_DECISION",
                        "由可靠性工程师复核合格现场证据并决定是否形成工单草稿",
                        "采集 PASS 只代表证据可用，不是自动最终结论。",
                        "RELIABILITY_ENGINEER",
                        blocking=True,
                        next_tool="draft_work_order",
                    )
                ]
            return [
                self._step(
                    "RECOLLECT_FIELD_EVIDENCE",
                    "按缺失通道和可比工况要求重新采集",
                    "PARTIAL/FAIL 现场结果不能升级工程结论。",
                    "FIELD_TECHNICIAN",
                    blocking=True,
                    next_tool="request_field_measurement",
                )
            ]
        monitoring = loaded.get("monitoring")
        if monitoring is not None and getattr(monitoring, "data_quality", None) == "CONFLICTING":
            return [
                self._step(
                    "CHECK_SENSOR_CHAIN",
                    "先检查传感器安装、供电、网关和数据连续性",
                    "数据质量冲突时不能先维修设备本体。",
                    "FIELD_TECHNICIAN",
                    blocking=True,
                ),
                self._step(
                    "REMEASURE_AFTER_CHECK",
                    "链路正常后在可比工况申请现场复测",
                    "用合格现场证据区分测量问题与真实振动异常。",
                    "RELIABILITY_ENGINEER",
                    consent=True,
                    next_tool="request_field_measurement",
                ),
            ]
        context = loaded.get("operating_context")
        missing = list(getattr(context, "missing_fields", []) if context else [])
        first = self._step(
            "VERIFY_OPERATING_CONTEXT",
            "补齐报警时工况并与监测趋势对齐",
            "负荷、转速和生产条件会直接影响监测特征的可比性。",
            "DUTY_ENGINEER",
            required_inputs=missing or ["报警时负荷", "转速/节拍", "近期启停或维修变化"],
            blocking=bool(missing),
            next_tool="get_operating_context",
        )
        if severity == "CRITICAL" and diagnosis_status == "ENGINEER_CONFIRMED":
            return [
                self._step(
                    "VERIFY_LIVE_SAFETY_CONTEXT",
                    "立即复核运行状态、保护/联锁与企业处置阈值",
                    "严重故障已确认且待行动，必须由现场状态触发授权决策。",
                    "DUTY_ENGINEER",
                    required_inputs=["当前负荷", "保护/联锁状态", "企业 SOP"],
                    blocking=True,
                ),
                self._step(
                    "DECIDE_MAINTENANCE_WINDOW",
                    "由授权工程师决定检修窗口或运行限制",
                    "系统不执行停机或控制，只保留证据和人工决策边界。",
                    "AUTHORIZED_APPROVER",
                    approval=True,
                    blocking=True,
                ),
            ]
        return [
            first,
            self._step(
                "REQUEST_FIELD_MEASUREMENT",
                "工况核对后仍异常时，征得同意安排现场补测",
                "现场证据用于确认或否定候选诊断。",
                "RELIABILITY_ENGINEER",
                consent=True,
                next_tool="request_field_measurement",
            ),
        ]

    def _assets(self, data: dict[str, Any]) -> GuidanceEnvelope:
        items = data.get("items", [])
        active = [item for item in items if item.get("active_fault_count", 0) > 0]
        if not active:
            return self._envelope(
                profile="NAVIGATION",
                summary="本页未发现活动调查记录；这不等于设备已被证明健康。",
                stage="ASSET_SCREENING",
                actionability="INFORM",
                steps=[
                    self._step(
                        "CHECK_MONITORING_COVERAGE",
                        "核对监测在线状态与数据新鲜度",
                        "无活动故障只说明目录中没有未关闭调查。",
                        "RELIABILITY_ENGINEER",
                    )
                ],
            )
        top = active[0]
        urgency = _SEVERITY_URGENCY.get(top.get("highest_active_severity"), "PRIORITY")
        return self._envelope(
            profile="NAVIGATION",
            summary=(
                f"本页有 {len(active)} 台设备存在活动故障；优先查看 {top['asset_name']}"
                f"（{top['asset_id']}，最高严重度 {top['highest_active_severity']}）。"
            ),
            urgency=urgency,
            stage="ASSET_SCREENING",
            actionability="INVESTIGATE",
            steps=[
                self._step(
                    "FILTER_ACTIVE_FAULTS",
                    f"读取 {top['asset_name']} 的活动故障",
                    "先确认具体故障、诊断成熟度和责任状态，再讨论处置。",
                    "SYSTEM",
                    required_inputs=[top["asset_id"]],
                    next_tool="list_current_faults",
                )
            ],
        )

    def _faults(self, data: dict[str, Any]) -> GuidanceEnvelope:
        items = data.get("items", [])
        if not items:
            return self._envelope(
                profile="NAVIGATION",
                summary="筛选条件下没有活动故障记录。",
                stage="FAULT_SCREENING",
                actionability="INFORM",
                steps=[
                    self._step(
                        "REVIEW_FILTERS",
                        "核对站点、产线、设备与时间过滤条件",
                        "避免因过滤范围过窄漏掉活动调查。",
                        "USER",
                    )
                ],
            )
        top = items[0]
        severity = top.get("severity", "INFO")
        why = (
            f"{severity} 且状态为 {top.get('fault_status')}，诊断成熟度为 "
            f"{top.get('diagnosis_status')}，更新时间在当前结果中最优先。"
        )
        questions = []
        escalation = []
        if severity in {"CRITICAL", "MAJOR"}:
            questions = ["当前运行状态、负荷和企业对应等级的处置 SOP 是否已由值班工程师核实？"]
            escalation = ["达到企业既定保护、停机或人员安全阈值时，立即升级授权工程师按 SOP 决策。"]
        return self._envelope(
            profile="NAVIGATION",
            summary=(
                f"共 {data.get('total', len(items))} 个活动故障；最值得关注的是 "
                f"{top['title']}（{top['fault_id']}，{severity}）。优先理由：{why}"
            ),
            urgency=_SEVERITY_URGENCY.get(severity, "ROUTINE"),
            stage="FAULT_PRIORITIZATION",
            actionability="INVESTIGATE",
            steps=[
                self._step(
                    "READ_PRIORITY_FAULT",
                    "读取最高优先级故障详情",
                    "详情将区分事实、推断、证据缺口和已有冲突。",
                    "SYSTEM",
                    required_inputs=[top["fault_id"]],
                    next_tool="get_fault_detail",
                ),
                self._step(
                    "ASSIGN_REVIEW_OWNER",
                    "确认本次调查的值班工程师",
                    "严重故障需要明确人工责任人，MCP 不替代授权决策。",
                    "DUTY_ENGINEER",
                    blocking=severity in {"CRITICAL", "MAJOR"},
                ),
            ],
            questions=questions,
            escalation=escalation,
        )

    def _fault_detail(self, data: dict[str, Any]) -> GuidanceEnvelope:
        fault = data.get("fault", {})
        severity = fault.get("severity", "INFO")
        diagnosis_status = fault.get("diagnosis_status", "CANDIDATE")
        fault_status = fault.get("fault_status", "OPEN")
        asset = data.get("asset") or {}
        fault_id = fault.get("fault_id", "当前故障")
        questions = list(data.get("open_questions") or [])[:2]
        if severity == "CRITICAL" and diagnosis_status == "ENGINEER_CONFIRMED":
            steps = [
                self._step(
                    "VERIFY_LIVE_SAFETY_CONTEXT",
                    "立即复核运行状态与现有保护/联锁信息",
                    "目录结论不能替代当前现场状态；先确认是否已触发企业安全边界。",
                    "DUTY_ENGINEER",
                    required_inputs=["当前负荷", "备用机可用性", "保护/联锁状态", "企业处置 SOP"],
                    blocking=True,
                ),
                self._step(
                    "DECIDE_MAINTENANCE_WINDOW",
                    "由授权工程师决定检修窗口或运行限制",
                    "故障已确认且待行动，但停机与生产调整必须按企业权限和 SOP 决策。",
                    "AUTHORIZED_APPROVER",
                    required_inputs=["现场复核结果", "生产影响", "企业阈值"],
                    approval=True,
                    blocking=True,
                ),
            ]
            questions = ["当前负荷、备用机可用性及企业停机/降载阈值是否已经核实？"]
        elif severity == "MAJOR" and diagnosis_status == "INCONCLUSIVE":
            steps = [
                self._step(
                    "CHECK_SENSOR_CHAIN",
                    "检查传感器安装、供电、网关和数据连续性",
                    "当前证据存在数据质量风险，必须先区分测量链路问题与设备真实异常。",
                    "FIELD_TECHNICIAN",
                    required_inputs=["安装紧固", "网关日志", "原始采集状态"],
                    blocking=True,
                ),
                self._step(
                    "REQUEST_COMPARABLE_MEASUREMENT",
                    "在可比工况下申请现场复测",
                    "传感链检查后仍异常，才能用合格补测推进工程判断。",
                    "RELIABILITY_ENGINEER",
                    consent=True,
                    next_tool="create_evaluation_session",
                ),
            ]
        else:
            missing = (data.get("operating_context") or {}).get("missing_fields", [])
            steps = [
                self._step(
                    "COMPLETE_OPERATING_CONTEXT",
                    "补齐报警时工况并核对监测趋势",
                    "候选诊断需要在可比负荷、转速和生产条件下复核。",
                    "RELIABILITY_ENGINEER",
                    required_inputs=missing or ["报警时负荷", "转速/节拍", "近期启停或维修变化"],
                    blocking=bool(missing),
                    next_tool="get_operating_context",
                )
            ]
            if data.get("recommended_actions"):
                steps.append(
                    self._step(
                        "PREPARE_FIELD_EVIDENCE",
                        "证据仍不足时征得同意安排现场补测",
                        "现场证据用于确认或否定候选诊断，不能自动生成最终结论。",
                        "RELIABILITY_ENGINEER",
                        consent=True,
                        next_tool="create_evaluation_session",
                    )
                )
        return self._envelope(
            profile="EVIDENCE",
            summary=(
                f"{asset.get('asset_name', asset.get('asset_id', '设备'))} 的 {fault_id} 为 "
                f"{severity}/{diagnosis_status}/{fault_status}；下一步必须由当前证据状态决定。"
            ),
            urgency=_SEVERITY_URGENCY.get(severity, "ROUTINE"),
            stage=f"{diagnosis_status}:{fault_status}",
            actionability="DECISION_PENDING" if severity == "CRITICAL" else "INVESTIGATE",
            steps=steps,
            questions=questions,
            escalation=[
                "现场状态达到企业既定安全或保护阈值时，升级授权人员按 SOP 处理。",
                "证据冲突、数据质量不合格或现场结果未通过时，不得升级诊断结论。",
            ],
        )

    def _history(self, data: dict[str, Any]) -> GuidanceEnvelope:
        items = data.get("items", [])
        validated = sum(item.get("diagnosis_status") == "VALIDATED" for item in items)
        rejected = sum(item.get("diagnosis_status") == "REJECTED" for item in items)
        return self._envelope(
            profile="EVIDENCE",
            summary=(
                f"检索到 {len(items)} 条历史，其中已验证 {validated} 条、"
                f"已驳回 {rejected} 条；历史仅用于安排本次调查优先级。"
            ),
            stage="HISTORICAL_COMPARISON",
            actionability="INVESTIGATE",
            steps=[
                self._step(
                    "VERIFY_CURRENT_CASE",
                    "回到本次监测、工况和现场证据进行验证",
                    "相似历史同时存在成功、否定或未定结局，不能直接套用维修动作。",
                    "RELIABILITY_ENGINEER",
                    next_tool="get_monitoring_summary",
                )
            ],
            escalation=["只有本次证据达到企业工程确认标准时，才升级诊断或处置。"],
        )

    def _evidence(
        self, tool_name: str, data: dict[str, Any], *, fault: Mapping[str, Any] | None
    ) -> GuidanceEnvelope:
        severity = (fault or {}).get("severity", "WARNING")
        urgency = _SEVERITY_URGENCY.get(severity, "PRIORITY")
        fault_id = data.get("fault_id", "当前故障")
        if tool_name == "get_monitoring_summary":
            quality = data.get("data_quality")
            if quality in {"CONFLICTING", "POOR", "INVALID"}:
                return self._envelope(
                    profile="EVIDENCE",
                    summary=(
                        f"{fault_id} 的监测数据质量为 {quality}，"
                        "当前趋势不能单独支持设备本体故障结论。"
                    ),
                    urgency=urgency,
                    stage="DATA_QUALITY_REVIEW",
                    actionability="INVESTIGATE",
                    steps=[
                        self._step(
                            "CHECK_SENSOR_CHAIN",
                            "先检查传感器与采集链路",
                            "排除安装、供电、通信和丢包造成的伪异常。",
                            "FIELD_TECHNICIAN",
                            blocking=True,
                        ),
                        self._step(
                            "VERIFY_IN_FIELD",
                            "链路正常后在可比工况复测",
                            "只有质量合格的现场证据才能推进工程判断。",
                            "RELIABILITY_ENGINEER",
                            consent=True,
                            next_tool="create_evaluation_session",
                        ),
                    ],
                    questions=["传感器安装、网关日志和数据缺口是否已经现场核实？"],
                )
            return self._envelope(
                profile="EVIDENCE",
                summary=(
                    f"{fault_id} 的监测状态为 {data.get('overall_status')}，"
                    f"趋势为“{data.get('trend')}”；仍需与报警时工况对齐。"
                ),
                urgency=urgency,
                stage="TREND_VERIFICATION",
                actionability="INVESTIGATE",
                steps=[
                    self._step(
                        "ALIGN_OPERATING_CONTEXT",
                        "核对报警时负荷、转速和生产条件",
                        "趋势脱离工况不能区分设备异常与正常负载响应。",
                        "RELIABILITY_ENGINEER",
                        next_tool="get_operating_context",
                    )
                ],
            )
        if tool_name == "get_operating_context":
            missing = data.get("missing_fields", [])
            return self._envelope(
                profile="EVIDENCE",
                summary=(
                    f"{fault_id} 的工况仍缺少：{', '.join(missing)}。"
                    if missing
                    else f"{fault_id} 已取得当前工况，可进入跨证据复核。"
                ),
                urgency=urgency,
                stage="CONTEXT_COMPLETION",
                actionability="INVESTIGATE",
                steps=[
                    self._step(
                        "FILL_BLOCKING_CONTEXT" if missing else "COMPARE_EVIDENCE",
                        "补齐阻塞工况字段" if missing else "将工况与监测和同类设备对齐",
                        "缺失字段会影响可比性。"
                        if missing
                        else "工况一致时，监测差异才具有调查价值。",
                        "DUTY_ENGINEER" if missing else "RELIABILITY_ENGINEER",
                        required_inputs=missing,
                        blocking=bool(missing),
                        next_tool=None if missing else "compare_peer_assets",
                    )
                ],
                questions=[f"能否提供 {', '.join(missing)}？"] if missing else [],
            )
        if tool_name == "get_maintenance_history":
            records = data.get("records", [])
            return self._envelope(
                profile="EVIDENCE",
                summary=(
                    f"{fault_id} 取得 {len(records)} 条维修记录；时间关联不等于本次故障的因果证据。"
                ),
                urgency=urgency,
                stage="MAINTENANCE_CORRELATION",
                actionability="INVESTIGATE",
                steps=[
                    self._step(
                        "COMPARE_BEFORE_AFTER",
                        "核对维修前后同工况趋势及施工项目",
                        "用于判断维修后变化是否可重复，并避免直接归因。",
                        "RELIABILITY_ENGINEER",
                        required_inputs=["维修前后可比工况", "施工/更换项目", "维修后趋势"],
                        next_tool="get_monitoring_summary",
                    )
                ],
            )
        comparability = data.get("comparability")
        return self._envelope(
            profile="EVIDENCE",
            summary=f"{fault_id} 的同类对比可比性为 {comparability}；{data.get('analysis', '')}",
            urgency=urgency,
            stage="PEER_COMPARISON",
            actionability="INVESTIGATE",
            steps=[
                self._step(
                    "USE_PEERS_CONDITIONALLY",
                    "仅在同型号、同负荷和数据质量可比时使用对比结果",
                    "同类差异可提高调查优先级，但不能替代本机现场证据。",
                    "RELIABILITY_ENGINEER",
                    required_inputs=data.get("limitations", []),
                    next_tool="request_field_measurement"
                    if comparability == "GOOD"
                    else "get_operating_context",
                )
            ],
        )

    def _intake(self, tool_name: str, data: dict[str, Any]) -> GuidanceEnvelope:
        payload = data.get("data", data)
        task_id = payload.get("task_id", "新任务")
        return self._envelope(
            profile="INTAKE",
            summary=f"已创建隔离调查任务 {task_id}，当前只载入初始模拟报警，尚未形成最终工程结论。",
            urgency="PRIORITY",
            stage="ALARM_RECEIVED",
            actionability="INVESTIGATE",
            steps=[
                self._step(
                    "START_INVESTIGATION",
                    "读取任务并开始证据调查",
                    "先核对报警、工况和监测，再决定是否补测。",
                    "SYSTEM",
                    required_inputs=[task_id],
                    next_tool="agent_invoke"
                    if tool_name == "create_evaluation_session"
                    else "get_task",
                )
            ],
        )

    def _field_request(self, data: dict[str, Any]) -> GuidanceEnvelope:
        status = "新建" if data.get("created") else "复用已有"
        return self._envelope(
            profile="FIELD_EVIDENCE",
            summary=(
                f"已{status}现场补测请求 {data.get('request_id')}；结果返回前不能升级工程结论。"
            ),
            urgency="PRIORITY",
            stage="FIELD_EVIDENCE_PENDING",
            actionability="INVESTIGATE",
            steps=[
                self._step(
                    "COLLECT_FIELD_DATA",
                    "由现场人员在可比工况完成指定测点采集",
                    "采集质量必须为 PASS 才能进入人工工程判断。",
                    "FIELD_TECHNICIAN",
                    required_inputs=[
                        data.get("measurement_point_id", "指定测点"),
                        "可比工况",
                        "结构化声学与振动摘要",
                    ],
                    blocking=True,
                    next_tool="ingest_field_measurement_result",
                )
            ],
            questions=["现场采集的负荷、转速和测点安装状态是否与报警时可比？"],
        )

    def _field_result(
        self, data: dict[str, Any], *, collection_quality: str | None
    ) -> GuidanceEnvelope:
        quality = collection_quality or data.get("collection_quality") or "UNKNOWN"
        if quality == "PASS":
            steps = [
                self._step(
                    "ENGINEERING_REVIEW",
                    "由可靠性工程师复核现场证据并决定是否形成工单草稿",
                    "PASS 只表示采集质量合格，不等于故障已自动确认。",
                    "RELIABILITY_ENGINEER",
                    blocking=True,
                    next_tool="draft_work_order",
                )
            ]
            actionability = "DECISION_PENDING"
            summary = "现场补测质量 PASS，可进入人工工程判断。"
        else:
            steps = [
                self._step(
                    "RECOLLECT_FIELD_DATA",
                    "补齐或重新采集不合格现场数据",
                    "PARTIAL/FAIL 证据不得用于升级诊断或生成工单。",
                    "FIELD_TECHNICIAN",
                    required_inputs=["缺失通道", "可比工况", "采集质量说明"],
                    blocking=True,
                    next_tool="request_field_measurement",
                )
            ]
            actionability = "INVESTIGATE"
            summary = f"现场补测质量 {quality}，证据门控未通过。"
        return self._envelope(
            profile="FIELD_EVIDENCE",
            summary=summary,
            urgency="PRIORITY",
            stage="FIELD_EVIDENCE_REVIEW",
            actionability=actionability,
            steps=steps,
        )

    def _draft(self, data: dict[str, Any]) -> GuidanceEnvelope:
        response_data = data.get("data", data.get("response", {}).get("data", {}))
        approval = response_data.get("pending_approval")
        if approval:
            return self._envelope(
                profile="DECISION_TRANSITION",
                summary=(
                    f"已生成模拟工单草稿，审批 {approval.get('approval_id')} 待一次性人工决定。"
                ),
                urgency="URGENT",
                stage="APPROVAL_PENDING",
                actionability="APPROVAL_REQUIRED",
                steps=[
                    self._step(
                        "REVIEW_AND_DECIDE",
                        "核对影响预览、证据版本后明确批准或拒绝",
                        "Challenge 一次性且绑定当前证据版本，不能重放。",
                        "AUTHORIZED_APPROVER",
                        required_inputs=["影响预览", "approval_challenge", "evidence_version"],
                        approval=True,
                        blocking=True,
                        next_tool="decide_work_order_approval",
                    )
                ],
            )
        return self._envelope(
            profile="DECISION_TRANSITION",
            summary="工单草稿门控未通过，当前没有可审批草稿。",
            urgency="PRIORITY",
            stage="EVIDENCE_GATE_BLOCKED",
            actionability="INVESTIGATE",
            steps=[
                self._step(
                    "COMPLETE_QUALIFIED_EVIDENCE",
                    "先取得质量 PASS 的现场补测并完成工程复核",
                    "无合格现场证据时禁止生成工单。",
                    "RELIABILITY_ENGINEER",
                    blocking=True,
                    next_tool="request_field_measurement",
                )
            ],
        )

    def _approval(self, data: dict[str, Any], *, decision: str | None) -> GuidanceEnvelope:
        approved = decision == "APPROVE"
        return self._envelope(
            profile="DECISION_TRANSITION",
            summary="审批已批准；一次性 Challenge 已消费。"
            if approved
            else "审批已拒绝；一次性 Challenge 已消费。",
            urgency="URGENT" if approved else "PRIORITY",
            stage="WORK_ORDER_APPROVED" if approved else "WORK_ORDER_REJECTED",
            actionability="INVESTIGATE" if approved else "COMPLETE",
            steps=[
                self._step(
                    "REPORT_COMPLETION" if approved else "PRESERVE_REJECTION",
                    "维修完成后回传实际发现与维修后验证"
                    if approved
                    else "保留拒绝意见；如需重提必须补充新证据",
                    "批准不代表维修已完成。"
                    if approved
                    else "拒绝结论不能通过重放旧 Challenge 绕过。",
                    "MAINTENANCE_TEAM" if approved else "RELIABILITY_ENGINEER",
                    next_tool="ingest_work_order_completion" if approved else "get_task",
                )
            ],
        )

    def _completion(self, data: dict[str, Any]) -> GuidanceEnvelope:
        payload = data.get("data", data)
        validation = payload.get("maintenance_validation") or {}
        status = str(validation.get("status") or payload.get("task_state") or "REVIEW_REQUIRED")
        improved = any(
            word in status.upper() for word in ("VALIDATED", "IMPROVED", "CLOSED", "COMPLETED")
        )
        return self._envelope(
            profile="VALIDATION_ORCHESTRATION",
            summary=(
                "维修后结果已显示改善，仍需保存验证证据后关闭。"
                if improved
                else "维修完成已回传，但维修后效果仍需复核，不能自动关闭调查。"
            ),
            urgency="PRIORITY",
            stage="POST_MAINTENANCE_VALIDATION",
            actionability="COMPLETE" if improved else "INVESTIGATE",
            steps=[
                self._step(
                    "VERIFY_POST_MAINTENANCE",
                    "在可比工况核对维修前后趋势并读取任务状态",
                    "实际发现、采取动作和维修后诊断必须相互一致。",
                    "RELIABILITY_ENGINEER",
                    required_inputs=["维修后可比工况", "趋势变化", "实际故障与动作"],
                    blocking=not improved,
                    next_tool="get_task",
                )
            ],
        )

    def _task(self, data: dict[str, Any], *, task_state: str | None) -> GuidanceEnvelope:
        state = task_state or data.get("task_state", "UNKNOWN")
        if data.get("pending_approval"):
            step = self._step(
                "DECIDE_PENDING_APPROVAL",
                "处理当前一次性审批",
                "审批已待处理，不应重新生成 Challenge。",
                "AUTHORIZED_APPROVER",
                approval=True,
                blocking=True,
                next_tool="decide_work_order_approval",
            )
            actionability = "APPROVAL_REQUIRED"
        elif state == "FIELD_EVIDENCE_PENDING":
            step = self._step(
                "WAIT_OR_INGEST_FIELD_RESULT",
                "等待并回传现场补测结果",
                "任务需要质量门控后的现场证据。",
                "FIELD_TECHNICIAN",
                blocking=True,
                next_tool="ingest_field_measurement_result",
            )
            actionability = "INVESTIGATE"
        elif data.get("maintenance_validation"):
            step = self._step(
                "REVIEW_MAINTENANCE_VALIDATION",
                "复核维修后验证并决定关闭或重开调查",
                "维修完成不等于效果已验证。",
                "RELIABILITY_ENGINEER",
                next_tool="agent_invoke",
            )
            actionability = "DECISION_PENDING"
        else:
            step = self._step(
                "CONTINUE_EVIDENCE_REVIEW",
                "根据当前状态继续最小必要的证据调查",
                "任务快照显示尚无待审批或完成验证。",
                "RELIABILITY_ENGINEER",
                next_tool="agent_invoke",
            )
            actionability = "INVESTIGATE"
        return self._envelope(
            profile="VALIDATION_ORCHESTRATION",
            summary=f"任务 {data.get('task_id')} 当前状态为 {state}；下一步由该状态唯一确定。",
            urgency=_SEVERITY_URGENCY.get((data.get("alarm") or {}).get("severity"), "PRIORITY"),
            stage=state,
            actionability=actionability,
            steps=[step],
        )

    def _agent(
        self,
        data: dict[str, Any],
        *,
        fault: Mapping[str, Any] | None,
        task_state: str | None,
    ) -> GuidanceEnvelope:
        response = data.get("response", data)
        response_data = response.get("data", response)
        severity = (fault or {}).get("severity", "WARNING")
        questions = [
            item.get("question", "")
            for item in response_data.get("open_questions", [])
            if item.get("blocking")
        ]
        actions = response_data.get("recommended_actions", [])
        steps = [
            self._step(
                item.get("code", "NEXT_ACTION"),
                item.get("label", "继续调查"),
                item.get("why", "该动作由当前证据和任务状态触发。"),
                item.get("owner", "RELIABILITY_ENGINEER"),
                required_inputs=item.get("required_inputs", []),
                consent=item.get("requires_consent", False),
                approval=item.get("requires_approval", False),
                blocking=item.get("blocking", False),
                next_tool=item.get("next_tool"),
            )
            for item in actions
        ]
        if not steps:
            steps = [
                self._step(
                    "REVIEW_RESPONSE",
                    "按回答中的证据缺口继续调查",
                    "Agent 不会自动执行生产控制。",
                    "RELIABILITY_ENGINEER",
                )
            ]
        return self._envelope(
            profile="VALIDATION_ORCHESTRATION",
            summary=f"Agent 已按 {severity} 严重度、证据缺口和任务状态生成本轮行动方案。",
            urgency=_SEVERITY_URGENCY.get(severity, "PRIORITY"),
            stage=task_state or response_data.get("task_state", "EVIDENCE_REVIEW"),
            actionability="APPROVAL_REQUIRED"
            if response_data.get("pending_approval")
            else "INVESTIGATE",
            steps=steps,
            questions=questions,
            escalation=[
                "达到企业既定安全或保护阈值时，由授权人员按 SOP 决定停机、降载或其他措施。"
            ],
        )
