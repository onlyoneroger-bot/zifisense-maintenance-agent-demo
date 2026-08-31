# LLM 能力接入方案

## 1. 当前状态

Sprint 2A 已接入 DeepSeek。项目使用官方 OpenAI Python SDK 调用 DeepSeek 的 OpenAI-compatible Chat Completions 接口，默认模型为 `deepseek-v4-flash`，并通过 JSON Output 与 Pydantic 校验模型结果。

- `LLM_ENABLED=false` 是默认安全基线，不要求 Key，也不构造公网客户端。
- `LLM_ENABLED=true` 时，DeepSeek 只对安全的只读调查答案做基于证据的表达增强。
- 规则意图路由、工具执行、状态机、补测同意、审批 Challenge 和会话隔离仍由服务端代码裁决。
- 供应商异常、空响应、无效 JSON 或虚构证据 ID 会回退到确定性答案，并标记 `meta.is_degraded=true`。
- CI 使用 Fake Provider；未配置真实 Key 时不声称实网模型测试通过。

## 2. 目标与约束

### 目标

- 用 LLM 改善自然语言理解、问题分解、工具选择和回答表达。
- 保持现有 REST、MCP Tool 名称、响应 Schema 和任务状态机兼容。
- 支持关闭 LLM 后继续运行当前确定性模式。
- 为后续更换 OpenAI、Azure OpenAI、其他云模型或兼容网关保留接口。

### 不可突破的边界

- LLM 不直接写数据库，不直接调用 EAM、PLC 或 DCS。
- LLM 不直接批准工单，不生成或绕过一次性审批 Challenge。
- 补测仍要求用户明确同意；写操作仍由现有状态机和 Pydantic Schema 校验。
- 原始高频振动波形不发送给通用 LLM，只发送已脱敏的结构化特征和摘要。
- 模型生成内容不得升级为“已确认故障”；事实、推断、人工描述和证据继续分层保存。

## 3. 现有方案比较

| 方案 | 需求覆盖 | 接入成本 | 复杂度 | 可维护性 | 主要风险 | 适用性 |
|---|---|---:|---:|---:|---|---|
| 官方模型 SDK + 项目内 `LLMProvider` | 单一供应商、结构化输出、工具调用 | 低 | 低 | 高 | 供应商特性需要适配 | 最适合 P0；不会改写现有安全架构 |
| Pydantic AI | 多供应商、结构化输出、工具、测试模型 | 中 | 中 | 高 | 引入新的 Agent 抽象，可能与现有状态机职责重叠 | 适合确定多供应商需求后采用 |
| LiteLLM SDK/Proxy | 100+ 模型、重试、路由、预算、网关 | 中到高 | 高 | 中到高 | 增加网关、运维面和供应链依赖 | 适合多团队、集中成本治理或多云容灾 |

推荐顺序：P0 使用官方 SDK，但所有调用隐藏在项目自有 `LLMProvider` 接口之后；P1 根据实际多供应商需求选择 Pydantic AI 或 LiteLLM Gateway。不要在首期同时引入多个 Agent 框架。

参考资料：

- [DeepSeek Function Calling 与 OpenAI-compatible 示例](https://api-docs.deepseek.com/guides/function_calling)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- [DeepSeek Chat Completion API](https://api-docs.deepseek.com/api/create-chat-completion/)
- [OpenAI Developer Quickstart](https://platform.openai.com/docs/quickstart/make-your-first-api-request)
- [OpenAI 数据控制说明](https://developers.openai.com/api/docs/guides/your-data)
- [Pydantic AI Structured Output](https://pydantic.dev/docs/ai/core-concepts/output/)
- [Pydantic AI Model Providers](https://pydantic.dev/docs/ai/models/overview/)
- [LiteLLM 官方文档](https://docs.litellm.ai/)

## 4. 当前架构（Sprint 2B）

Sprint 2B 已增加确定性 Guidance Engine。项目没有把 Tool 选择权交给模型；原因是比赛 Demo 的状态机、补测同意和一次性审批需要可重复验收。当前链路如下：

```text
REST / MCP 请求
      │
      ▼
认证、会话隔离、越权词与显式同意前置检查
      │
      ▼
读取任务、报警、结构化证据和历史对话
      │
      ├── LLM_ENABLED=false ──► 当前确定性 AgentFacade
      │
      ▼
确定性意图路由与现有 Service 执行工具
      │
      ▼
Guidance Engine：统一契约、六类策略、状态与安全规则
      │
      ▼
可选 DeepSeek Synthesizer：只改写答案并选择已有证据 ID
      │
      ▼
Canonical Response Builder：重建事实、证据引用、审批与状态字段
      │
      ▼
持久化审计信息并返回现有 AgentInvokeResponse
```

最终 `guidance`、`recommended_actions`、`task_state`、`pending_approval`、`evidence`、`tool_executions` 和写操作结果全部由服务端代码生成。模型不能增加动作、阈值、证据或审批结论。

## 5. Sprint 2A 代码结构

```text
src/zifisense_agent_api/
  adapters/llm/
    base.py                   # LLMProvider Protocol
    deepseek.py               # DeepSeek OpenAI-compatible Adapter
    factory.py                # 启用/禁用与配置装配
  domain/
    llm_models.py             # 请求、证据、结构化结果与增强结果
```

已调整：

- `config.py`：新增 LLM 配置并做条件校验。
- `main.py`：创建 Provider 并注入 `AgentFacade`。
- `agent_facade.py`：保留现有确定性路径；只在安全的只读意图完成后调用回答合成。
- 现有响应 Schema 不新增必填字段；调用结果写入 `tool_executions`，失败使用既有 `meta.is_degraded`。
- 三评委 Harness 保持确定性基线；LLM 专项 Profile 留待 Sprint 2C。

## 6. Sprint 2B Guidance 数据模型

```python
class GuidanceEnvelope(BaseModel):
    profile: GuidanceProfile
    summary: str
    urgency: GuidanceUrgency
    current_stage: str
    actionability: GuidanceActionability
    next_steps: list[GuidanceStep]
    blocking_questions: list[str]
    escalation_conditions: list[str]
    constraints: list[str]
    recommended_next_tools: list[str]
```

17 个 MCP Tool 共用上述契约，但分别使用导航、证据、现场补测、审批和维修验证策略。写操作仍由服务端门控，不由模型自主发起。

## 7. 已实现配置

```dotenv
LLM_ENABLED=false
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=
LLM_TIMEOUT_SECONDS=20
LLM_MAX_RETRIES=2
LLM_MAX_OUTPUT_TOKENS=1200
LLM_PROMPT_VERSION=maintenance-agent-v1
LLM_DAILY_BUDGET_CNY=10.00
LLM_BUDGET_TIMEZONE=Asia/Shanghai
LLM_USD_TO_CNY_RATE=7.00
DEEPSEEK_INPUT_CACHE_HIT_USD_PER_MILLION=0.014
DEEPSEEK_INPUT_CACHE_MISS_USD_PER_MILLION=0.44
DEEPSEEK_OUTPUT_USD_PER_MILLION=1.32
```

行为规则：

- `LLM_ENABLED=false` 时不要求 API Key，所有现有测试和比赛基线保持不变。
- `LLM_ENABLED=true` 时，启动阶段检查 Provider、模型和 API Key；缺失时快速失败并给出明确错误。
- `LLM_BASE_URL` 默认使用 DeepSeek 官方端点；当前不要留空。
- 日志、Trace、异常和响应中不得出现 API Key、完整系统提示词或原始敏感输入。
- 每次调用前按峰值价格预占当日预算；成功后按 DeepSeek usage 结算，异常时保守核销预占额。

### 完成实现后的本地配置方式

仓库已经忽略 `.env`，实现完成后可执行：

```powershell
Copy-Item .env.example .env
```

然后只在本地 `.env` 中填写：

```dotenv
LLM_ENABLED=true
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=<项目 API Key>
```

此配置已生效。启动后，安全的调查类 `agent_invoke` 会增加一条 `llm_answer_synthesis` 执行记录。

生产环境应使用云 Secret Manager、Kubernetes Secret 或部署平台的密钥变量，不把 API Key 写入 Compose、镜像、Git、日志或参赛附件。

## 8. 运行与降级策略

- 单次安全调查类 `agent/invoke` 最多一次模型请求，只做回答合成。
- 模型不执行工具；规则路由和现有服务先完成受控工具调用。
- Provider 超时、429、5xx、Schema 校验失败或内容安全失败时，回退到当前确定性 `AgentFacade`。
- 降级响应保持 HTTP 200 和现有业务 Schema，但 `meta.is_degraded=true`，同时记录标准化错误类别。
- 不把 Provider 原始异常文本直接返回给客户端，避免泄露请求和服务配置。
- 模型不可用不能影响 MCP 查询工具；只有 `agent_invoke` 的表达和规划能力降级。
- 北京时间当日预算不足时不调用模型，返回确定性答案并记录 `SKIPPED/BUDGET_GATE`。

## 8.1 每日预算门禁

预算以人民币微元整数保存在 SQLite 中。`llm_daily_budgets` 保存每天的限额、已消费和并发预占金额，`llm_usage_ledger` 保存逐次请求的 Token 分类、预占、结算和状态。

请求前使用系统提示词与请求 JSON 的 UTF-8 字节数作为输入 Token 上界，并按缓存全未命中、峰值输入价格和最大输出 Token 预占。SQLite 条件更新保证并发下 `spent + reserved + new_reservation` 不超过当日限额。成功后使用 `prompt_cache_hit_tokens`、`prompt_cache_miss_tokens` 和 `completion_tokens` 结算；超时、402、429、5xx 或 usage 缺失时按预占额核销，避免失联请求漏账。

这项门禁只覆盖使用同一预算数据库、通过本服务发出的请求。正式部署应为项目使用独立 DeepSeek Key；其他程序绕过本服务直接使用同一 Key 的费用不受本门禁控制。

## 9. 测试与验收标准

### P0 必须通过

1. `LLM_ENABLED=false` 时，现有确定性测试全部保持通过。
2. 使用 Fake Provider 验证输入构造、结构化合成、引用和持久化，不依赖真实 API Key。
3. Provider 超时、429、5xx、无效 JSON 和 Schema 不匹配均能确定性降级。
4. Prompt Injection 不能越过工具白名单、会话隔离、补测同意和审批 Challenge。
5. 模型不能直接修改 `task_state`、`evidence_version`、审批状态或工作单状态。
6. 工具结果中的 `evidence_id` 才能进入引用；模型虚构的 ID 必须被拒绝。
7. 日志、报告、Trace 和异常中不包含 API Key。
8. 实网模型测试为显式 opt-in；CI 默认使用 Fake Provider。
9. OpenAPI、REST 与 MCP 的现有响应字段保持向后兼容。

### P1

- 记录模型延迟、Token、错误类别、降级率和按请求估算成本。
- 新增 LLM Harness Profile，包含越权提示、无证据结论、工具参数注入和引用幻觉测试。
- 建立固定评测集，比较确定性基线与 LLM 模式的意图准确率、工具选择准确率和证据引用正确率。

## 10. Sprint 建议

### Sprint 2A：基础 Provider 与安全降级

- 配置、`LLMProvider`、DeepSeek Adapter、Fake Provider。
- 仅用 LLM 生成回答草稿，不开放模型工具选择。
- 保持现有规则路由和工具执行不变。

### Sprint 2B：确定性 Guidance 与受控编排（已实现）

- 引入统一 Guidance 契约、六类策略和状态规则。
- 17 个 MCP Tool 增加 annotations、具体用途和处置下一步。
- 活动目录故障可进入隔离会话；停机问题进入证据化决策支持。
- 保持 DeepSeek 只负责表达增强，不开放模型自主写工具。

### Sprint 2C：评测、观测与多供应商准备

- 新增 LLM Harness Profile、质量数据集、成本与延迟统计。
- 根据实际需要评估 Pydantic AI 或 LiteLLM Gateway。

## 11. 已确认的部署选择

1. 首个模型供应商为 DeepSeek，比赛环境允许访问公网模型 API。
2. 只向模型发送 Fixture 和脱敏结构化证据摘要，不发送原始波形、密钥或审批 Challenge。
3. 北京时间自然日硬预算为 10 元，预算不足时不请求模型。
4. 完全离线的确定性模式始终保留，作为比赛和故障降级基线。
