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

运行时 `tools/list` 返回每个 Tool 的完整 JSON Schema，本文件用于人工阅读。

## Tools

### `create_evaluation_session`

创建隔离评测会话并装载初始模拟报警。输入：`scenario_id`、`idempotency_key`、可选 `locale`。返回 `evaluation_session_id`、`conversation_id` 和 `task_id`，供后续 `agent_invoke` 与 `get_task` 使用。

### `list_assets`

查询设备目录。可选输入：`site_id`、`line_id`、`asset_type`、`monitoring_status`、`has_active_fault`、`keyword`、`cursor`、`limit`。支持稳定排序与游标分页。`active_fault_count=0` 只表示没有活动调查记录，不代表设备绝对健康。

### `list_current_faults`

查询仍处于调查、补证、处置或维修中的记录。可按厂区、产线、设备、严重度、业务状态、诊断成熟度、发现时间和是否需要人工介入筛选。结果包含专业诊断来源与算法版本。

### `get_fault_detail`

按 `fault_id` 返回专业诊断、确认事实、Agent 推断、限制、监测摘要、工况、相关历史、证据、冲突、待补问题和推荐动作。`include` 可选择模块，`history_limit` 范围 0～20。

### `list_fault_history`

查询已关闭、解决或驳回的历史记录。支持设备、厂区、产线、设备类型、故障模式、诊断状态、关闭时间和 `related_to_fault_id`。相关历史同时返回相似维度与差异维度，并保留 `VALIDATED`、`REJECTED`、`INCONCLUSIVE` 结局。

### `agent_invoke`

调用与 REST `POST /api/v1/agent/invoke` 相同的 Agent 服务。当前为基于已持久化报警的诚实降级路径：不伪造 LLM、RAG、工具执行、引用或审批能力。

### `get_task`

按 `evaluation_session_id + task_id` 读取持久化任务和初始报警。跨会话或不存在的任务返回 Tool Error。

## 安全和数据声明

- 当前目录数据全部为比赛 Fixture，输出携带 `is_simulated=true`。
- `diagnosis_status` 表示诊断成熟度；候选诊断不等于最终故障事实。
- 工具目录不存在 PLC/DCS 控制或直接停机能力。
- 查询工具不依赖 LLM；LLM 不可用时仍可稳定调用。
- 当前写操作仅限创建隔离评测会话，不写入真实工业系统。
