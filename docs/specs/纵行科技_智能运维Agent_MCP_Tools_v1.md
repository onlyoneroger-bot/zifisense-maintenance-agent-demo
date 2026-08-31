# ZiFiSense 智能运维 Agent MCP 公开接口 V1

## 接入

| 项目 | 值 |
|---|---|
| URL | `http(s)://<host>:8080/mcp` |
| Transport | Streamable HTTP，单 POST 端点 |
| JSON-RPC | 2.0 |
| 主协议 | `2026-07-28`，`server/discover` 探测，无会话 |
| 兼容协议 | `2025-11-25`，initialize 降级 |
| 认证 | `Authorization: Bearer <token>` |
| Client 标识 | 可选 `X-Client-Id` |
| 超时 | 所有当前 Tool 为同步只读或本地写入，目标 `<30s` |

部署方可通过 `API_CLIENTS_JSON` 发放多组独立账号与 API Key。客户端只需在每个 HTTP 请求中发送 Bearer Key；服务端根据 Key Hash 自动识别 `client_id`，不要求额外发送账号或密码。明文 Key 只在创建时交付一次，不写入仓库、镜像或本文档。

运行时 `tools/list` 返回每个 Tool 的完整 JSON Schema、中文标题、用途说明和副作用提示，本文件用于人工阅读。全部成功结果都增加 `guidance`；原有字段未删除。

### `guidance` 通用结构

`guidance` 不是一段固定建议，而是由 Tool 类型、故障严重度、诊断成熟度、证据质量和任务状态共同生成。主要字段如下：

| 字段 | 含义 |
|---|---|
| `profile` | `INTAKE`、`NAVIGATION`、`EVIDENCE`、`FIELD_EVIDENCE`、`DECISION_TRANSITION` 或 `VALIDATION_ORCHESTRATION` |
| `summary` | 本次结果对调查的具体意义 |
| `urgency` | `ROUTINE`、`PRIORITY`、`URGENT` 或 `CRITICAL` |
| `current_stage` | 当前调查、审批或验证阶段 |
| `actionability` | 当前可告知、需调查、待决策、待审批或已完成 |
| `next_steps` | 有顺序的动作，包含原因、责任角色、必需输入、同意/审批要求和可选下一 Tool |
| `blocking_questions` | 不回答就无法可靠推进的问题 |
| `escalation_conditions` | 需要升级人工或按企业 SOP 决策的条件 |
| `constraints` | 模拟数据、证据边界和禁止自动控制声明 |

## Tools

### `create_evaluation_session`

创建隔离评测会话并装载初始模拟报警。必须提供 `idempotency_key`，并在 `scenario_id` 与活动目录 `fault_id` 中恰好选择一个；`locale` 可选。返回 `evaluation_session_id`、`conversation_id` 和 `task_id`，供后续 `agent_invoke` 与 `get_task` 使用。六个活动目录故障均可由此进入闭环。

### `list_assets`

查询设备目录。可选输入：`site_id`、`line_id`、`asset_type`、`monitoring_status`、`has_active_fault`、`keyword`、`cursor`、`limit`。支持稳定排序与游标分页。`active_fault_count=0` 只表示没有活动调查记录，不代表设备绝对健康。

### `list_current_faults`

查询仍处于调查、补证、处置或维修中的记录。可按厂区、产线、设备、严重度、业务状态、诊断成熟度、发现时间和是否需要人工介入筛选。结果包含专业诊断来源与算法版本。

### `get_fault_detail`

按 `fault_id` 返回专业诊断、确认事实、Agent 推断、限制、监测摘要、工况、相关历史、证据、冲突、待补问题和推荐动作。`include` 可选择模块，`history_limit` 范围 0～20。

### `list_fault_history`

查询已关闭、解决或驳回的历史记录。支持设备、厂区、产线、设备类型、故障模式、诊断状态、关闭时间和 `related_to_fault_id`。相关历史同时返回相似维度与差异维度，并保留 `VALIDATED`、`REJECTED`、`INCONCLUSIVE` 结局。

### `get_monitoring_summary`

按当前 `fault_id` 查询近期监测趋势、已提取特征、数据质量和证据时间。返回的是模拟分析摘要，不接受原始高频时序数据，也不由 LLM 直接诊断波形。

### `get_operating_context`

按当前 `fault_id` 查询最近已知负荷、转速、节拍、配方、启停次数和缺失字段。数据新鲜度会明确标识，可用于驱动 Agent 追问报警时工况。

### `get_maintenance_history`

按当前 `fault_id` 返回相关资产的模拟维修记录、来源和证据标识，供本次调查关联使用；历史维修不自动证明本次故障原因。

### `compare_peer_assets`

按当前 `fault_id` 对比同产线可比设备的状态、监测指标和可比性，返回调查分析，不直接修改专业诊断置信度。

### `request_field_measurement`

在 `consent=true` 的明确同意条件下，为指定评测任务创建唯一的模拟现场补测请求。重复调用返回原请求，不重复调度；没有这个调用，补测结果不会被接收。

### `ingest_alarm`

向已有评测会话注入一条模拟专业报警并创建隔离任务。`event_id` 幂等；改变正文重放会返回冲突。

### `ingest_field_measurement_result`

回传专业便携分析服务生成的结构化声学和振动摘要。`PASS` 结果进入人工工程判断，`PARTIAL/FAIL` 保持待补证；不接收或伪造原始高频波形。

### `draft_work_order`

仅在存在质量合格的现场补测证据后创建模拟工单草稿，并返回一次性审批 Challenge。调用本身不会提交工单。

### `decide_work_order_approval`

使用 `approval_id + approval_challenge + evidence_version` 明确批准或拒绝。Challenge 只能使用一次、会过期；证据版本变化会安全失败。

### `ingest_work_order_completion`

回传模拟维修完成结果和结构化维修后诊断。改善则验证并关闭模拟任务；未改善或结论不足则保留冲突/待复核状态，不自动形成生产训练标签。

### `agent_invoke`

调用与 REST `POST /api/v1/agent/invoke` 相同的受控 Agent 服务。它按意图调用上述 Fixture 工具，保留事实、推断、证据和待补问题，并持久化多轮调查。每条推荐动作都给出原因、责任人、所需输入、阻塞状态及下一 Tool。启用 DeepSeek 时，模型只能改写确定性答案和引用已有证据，不能改变 Guidance、状态机或审批结果。

用户询问“是否需要停机/停线/降载”时，Agent 返回当前证据、缺失现场条件和企业 SOP 决策边界；它不会调用生产控制。用户要求“直接停机、无需人工确认”时仍按越权请求拒绝，且不产生工具副作用。

### `get_task`

按 `evaluation_session_id + task_id` 读取持久化任务、初始报警、对话轮次、人工声明、待审批及维修验证。`guidance` 根据当前状态只给出一条主路径，例如等待补测、处理审批、维修后验证或继续调查。跨会话或不存在的任务返回 Tool Error。

## Tool 副作用提示

- 只读且幂等：`list_assets`、`list_current_faults`、`get_fault_detail`、`list_fault_history`、四个证据查询 Tool、`get_task`。
- 写入但幂等：`create_evaluation_session`、`ingest_alarm`、`request_field_measurement`、`ingest_field_measurement_result`、`draft_work_order`、`ingest_work_order_completion`。
- 会记录新会话轮次：`agent_invoke`。
- 一次性且不可重放：`decide_work_order_approval`。

上述 annotations 是客户端提示，服务端认证、会话隔离、显式同意、证据门控和审批 Challenge 仍是最终安全边界。

## 安全和数据声明

- 当前目录数据全部为比赛 Fixture，输出携带 `is_simulated=true`。
- `diagnosis_status` 表示诊断成熟度；候选诊断不等于最终故障事实。
- 工具目录不存在 PLC/DCS 控制或直接停机能力。
- Guidance Engine 不依赖 LLM；LLM 关闭、失败或预算耗尽时仍返回完整处置步骤。
- 当前写操作仅限创建隔离评测会话、保存对话与未验证人工声明，以及明确同意后的模拟补测请求和结构化结果；不写入真实工业系统。
