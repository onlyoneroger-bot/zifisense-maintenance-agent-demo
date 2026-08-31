# Sprint Contract

## Sprint 1：三评委无 LLM 黑盒模拟环境

### 目标

- [x] 通过真实 HTTP 调用 REST API 与 MCP Streamable HTTP。
- [x] 实现业务、IT、Agent Harness 三个独立评委 Profile。
- [x] 输出可重放证据轨迹和 JSON、Markdown、JUnit 报告。
- [x] 提供 Docker Compose 环境和本地命令。
- [x] 不接入、调用或要求任何 LLM API。

### 文件清单

- `harness/__main__.py`
- `harness/client.py`
- `harness/core.py`
- `harness/judges.py`
- `harness/reporting.py`
- `harness/profiles/*.yaml`
- `harness/mcp-inspector.json`
- `Dockerfile.harness`
- `compose.harness.yaml`
- `tests/test_judge_harness.py`
- `docs/JUDGE_HARNESS.md`

### Definition of Done

- [x] 业务评委至少验证资产、当前故障、故障详情、历史故障、监测/工况/维修/同线数据、人工信息门控、补测同意与闭环状态。
- [x] IT 评委至少验证健康检查、认证、Scope、MCP `server/discover`、`tools/list`、工具 Schema、真实工具调用、幂等、错误结构和 10 并发。
- [x] Agent Harness 评委至少验证跨会话拒绝、范围外请求无工具副作用、现场补测显式同意、审批挑战/证据版本、防重放和无 PLC/DCS 工具。
- [x] 每个检查包含评委、类别、权重、通过状态、摘要、请求/响应证据引用；敏感 Header 不进入轨迹。
- [x] 轨迹为 append-only JSONL，每条记录包含前序哈希和当前哈希。
- [x] 任一 `hard_fail=true` 的检查失败时，总体结论必须为失败。
- [x] 报告同时生成 `report.json`、`report.md`、`junit.xml` 和 `trace.jsonl`。
- [x] Runner 有固定 seed、每评委最大步骤数、请求超时；超限或超时形成失败检查而不是无限等待。
- [x] Harness Docker 容器以非 root 用户运行，报告写入挂载目录。
- [x] 新增测试与原有测试全部通过，Ruff 无错误。

### 验证方法

1. `python -m pytest tests/test_judge_harness.py`
2. `python -m pytest`
3. `ruff check .`
4. 启动服务后运行 `python -m harness --base-url http://127.0.0.1:8080 --output reports`
5. 检查四种报告文件和最终退出码。

### Contract 确认

- [x] Generator 接受上述范围和完成标准。
- [x] Evaluator 已确认所有标准具体、可测且未包含 LLM 能力。
- [x] Contract 外新增要求需变更本文件。

Contract 创建时间：2026-08-29

Contract 状态：已完成

---

## Sprint 3：MCP 正式部署兼容性加固

### 目标

- [x] MCP Tool 使用 Bearer Token 对应的真实 `client_id`，不同账号的会话、任务和幂等键严格隔离。
- [x] 正式配置确保同步调用在对侧 30 秒超时前完成或确定性降级，不依赖 MCP 异步 Tasks。
- [x] 提供公网 HTTPS 生产 Compose、Caddy 反向代理模板、健康检查和部署检查清单。
- [x] 生产 MCP 限流配置不低于 6000 次/分钟，并提供单连接并发及吞吐探测脚本。
- [x] 使用官方 Python MCP SDK 完成 `server/discover`、`tools/list` 和真实 `tools/call` 验收。

### 文件清单

- `src/zifisense_agent_api/main.py`
- `src/zifisense_agent_api/config.py`
- `src/zifisense_agent_api/mcp_server.py`
- `tests/test_mcp.py`
- `tests/test_llm_integration.py`
- `tests/test_production_deployment.py`
- `.env.example`
- `.env.production.example`
- `compose.production.yaml`
- `Caddyfile`
- `scripts/mcp_sdk_smoke.py`
- `scripts/mcp_load_probe.py`
- `docs/PRODUCTION_DEPLOYMENT.md`
- `README.md`
- `.harness_context.md`
- `evaluation_report.md`

### Definition of Done

- [x] 两个不同 Bearer 账号可分别创建会话；相同幂等键不冲突，且账号 B 不能读取或调用账号 A 的任务。
- [x] `tools/list` 仍精确返回 17 个 Tool，注入的 SDK `Context` 不出现在 Tool JSON Schema 中。
- [x] 正式 LLM 配置为单次请求、无 SDK 自动重试；超时后保留确定性 Guidance，配置不能超过 25 秒同步预算。
- [x] 生产 Compose 只由 Caddy 暴露 80/443，应用端口只在容器网络可见；真实域名进入 MCP Host allowlist。
- [x] 生产 Compose 强制要求域名和 `API_CLIENTS_JSON`，不包含明文 Key；应用容器使用只读根文件系统、非 root 用户、健康检查和最小 Linux capabilities。
- [x] Caddy 支持 Streamable HTTP/SSE 透传并在 25 秒内限制上游响应头等待。
- [x] 官方 SDK Smoke Test 输出协商版本、Tool 数量和实际调用结果，不输出 Bearer Token。
- [x] 负载探测可限制为一个连接执行 10 并发，并报告成功率、吞吐量、p50/p95/p99；失败时退出非零。
- [x] Ruff、完整 Pytest、三评委 Harness、全量 REST/MCP 探测和官方 SDK Smoke Test全部通过。
- [x] 生成正式部署文档，明确 DNS、80/443、防火墙、证书、Secret、压测、回滚和发布前 Git 固化步骤。

### 验证方法

1. `.venv/Scripts/python.exe -m pytest tests/test_mcp.py tests/test_llm_integration.py tests/test_production_deployment.py`
2. `.venv/Scripts/python.exe -m pytest`
3. `.venv/Scripts/ruff.exe check .`
4. 启动隔离服务后运行 `scripts/mcp_sdk_smoke.py`
5. 运行 `scripts/mcp_load_probe.py --connections 1 --concurrency 10`
6. 解析 `compose.production.yaml`，并在有 Docker 的部署机执行 `docker compose -f compose.production.yaml config`、构建和健康检查。

### Contract 审查

- [x] 具体性：身份、超时、HTTPS、吞吐、Secret 和发布边界均有明确目标。
- [x] 可测试性：每项可由单测、配置解析、官方 SDK、并发探测或部署机验收验证。
- [x] 完整性：覆盖上一轮审查提出的四个阻塞项及 100 QPS 建议项。
- [x] 合理性：复用官方 MCP SDK、现有确定性降级和 SQLite 单实例架构；当前不引入完整 MCP Tasks。

### Contract 确认

- [x] Generator 接受上述范围和完成标准。
- [x] Evaluator 确认仅按上述标准验收。
- [x] 用户已明确要求按审查建议修复并准备正式部署。

Contract 创建时间：2026-08-31

本地验收结果：Pytest 92/92、REST/MCP 29/29、三评委 100/100、官方 SDK Smoke Test、200 请求负载探测（110.11 QPS，0 失败）及 Ruff 全部通过。本机无 Docker CLI，镜像构建、Caddy 证书签发和公网域名复验按部署手册在目标服务器执行。

Contract 状态：实现完成 / 本地验收通过 / 目标服务器部署门禁待执行

---

## Sprint 2C：三组账号与独立 API Key

### 目标

- [x] 从部署环境加载三组及以上“账号 + API Key Hash”，API Key 自动映射调用账号。
- [x] 保持 REST 与 MCP 现有 `Authorization: Bearer <API_KEY>` 契约兼容。
- [x] 保留原 `EVALUATOR_API_KEY_HASH`、`LIMITED_API_KEY_HASH` 作为未配置账号列表时的兼容回退。
- [x] 生成三组互不相同的正式随机 Key；明文不进入 Git、Docker 镜像、日志或测试报告。
- [x] 更新环境变量、Compose 和接入说明，并重新部署本机服务。

### 文件清单

- `src/zifisense_agent_api/config.py`
- `src/zifisense_agent_api/infrastructure/auth.py`
- `tests/test_auth.py`
- `tests/test_mcp.py`
- `.env.example`
- `compose.yaml`
- `README.md`
- `.env`（仅本地 Hash，不提交）
- `.harness_context.md`
- `evaluation_report.md`

### Definition of Done

- [x] `API_CLIENTS_JSON` 支持账号、SHA-256 Key Hash、Scope 和启停状态；拒绝重复账号、重复 Hash、非法 Hash 和空 Scope。
- [x] 配置三组账号后，每组 Key 均能认证并解析到正确 `client_id`；错误 Key 返回 401，缺 Scope 返回 403。
- [x] 三组账号均可使用 MCP `server/discover`、`tools/list` 和至少一个实际 Tool。
- [x] 未配置 `API_CLIENTS_JSON` 时，现有开发/测试 Key 和所有原有测试继续兼容。
- [x] 任何接口响应、日志、Harness 轨迹和受版本控制文件均不包含三组明文 Key。
- [x] Ruff、认证专项测试、完整 Pytest 和 MCP Smoke Test 通过。
- [x] 本机服务重新部署到 `127.0.0.1:8080`，三组 Key 逐一验证可连接。

### 验证方法

1. `python -m pytest tests/test_auth.py tests/test_mcp.py`
2. `python -m pytest`
3. `ruff check .`
4. 三组 Key 分别调用 `GET /api/v1/capabilities` 与 MCP `server/discover/tools/list/tools/call`
5. 扫描受版本控制文件，确认不存在交付的明文 Key

### Contract 审查

- [x] 具体性：账号来源、认证方式、兼容路径、密钥边界和部署目标明确。
- [x] 可测试性：三组成功、错误 Key、缺 Scope、MCP 调用和泄密扫描均可自动验证。
- [x] 完整性：覆盖配置、认证器、Compose、文档、测试和本机部署。
- [x] 合理性：复用现有 Bearer 中间件，不引入登录后台、JWT、OAuth 服务或完整 RBAC。

### Contract 确认

- [x] Generator 接受上述范围和完成标准。
- [x] Evaluator 确认仅按上述标准验收。
- [x] 用户已明确要求生成三组可用账号和 Key，并完成开发、部署。

Contract 创建时间：2026-08-31

Contract 完成时间：2026-08-31

Contract 状态：已完成

---

## Sprint 2B：MCP 处置引导与闭环改造

### 目标

- [x] 保持现有 17 个 MCP Tool 名称、REST 路径和原有响应字段兼容。
- [x] 所有 Tool 响应增加统一、结构化、可测试的 `guidance`，并按六类业务场景生成不同下一步。
- [x] 为全部 Tool 增加标题、用途说明及符合真实副作用语义的 MCP `ToolAnnotations`。
- [x] `agent_invoke` 输出由故障严重度、诊断成熟度、证据缺口和任务状态驱动，不再固定返回两条通用建议。
- [x] 停机/停线问题进入证据化决策支持，不执行或暗示已执行生产控制。
- [x] 目录内六个活动故障可通过兼容的 `create_evaluation_session(fault_id=...)` 进入调查会话。
- [x] DeepSeek 仅改写确定性答案；预算耗尽、禁用或失败时完整保留 Guidance。

### 文件清单

- `src/zifisense_agent_api/domain/guidance.py`
- `src/zifisense_agent_api/application/guidance_engine.py`
- `src/zifisense_agent_api/adapters/asset_fault_catalog.py`
- `src/zifisense_agent_api/application/evaluation_service.py`
- `src/zifisense_agent_api/application/agent_facade.py`
- `src/zifisense_agent_api/mcp_models.py`
- `src/zifisense_agent_api/mcp_server.py`
- `tests/test_guidance.py`
- `tests/test_mcp.py`
- `tests/test_agent_invoke.py`
- `docs/specs/纵行科技_智能运维Agent_MCP_Tools_v1.md`
- `docs/LLM_INTEGRATION_PLAN.md`
- `README.md`
- `.harness_context.md`
- `evaluation_report.md`

### Definition of Done

- [x] `tools/list` 精确返回 17 个 Tool；每个 Tool 均有非空 `title`、具体 `description` 和 annotations。
- [x] 九个查询类 Tool 标记只读、幂等、封闭世界；写 Tool annotations 与同意、审批及幂等语义一致，服务端门控保持权威。
- [x] 17 个 Tool 的成功结果均含合法 `guidance`；列表空结果、证据不足、补测 PASS/PARTIAL/FAIL、审批及维修验证分支均有明确下一步。
- [x] CRITICAL/MAJOR Guidance 包含优先级理由、顺序动作、执行角色、证据缺口、升级条件和阻塞问题；WARNING/INFO 不无依据建议停机或更换部件。
- [x] 询问停机/停线时意图为 `SAFETY_DECISION`，回答包含人工/SOP 边界且没有生产控制 ToolExecution。
- [x] `create_evaluation_session` 支持原 `scenario_id` 和新增 `fault_id` 两种入口，要求恰好选择一种；六个目录活动故障均可创建隔离会话并调用 `agent_invoke`。
- [x] DeepSeek 关闭、失败或预算拒绝时 Guidance 与确定性行动方案不丢失，10 元/日硬预算逻辑不变。
- [x] 全量 Pytest、Ruff、OpenAPI 合同、REST/MCP 探测、17/17 Tool 调用及三评委 Harness 通过。
- [x] 本地服务重新部署到 `127.0.0.1:8080/mcp`，健康检查、MCP discovery、tools/list 和自然语言 Smoke Test 通过。

### 验证方法

1. `python -m pytest tests/test_guidance.py tests/test_mcp.py tests/test_agent_invoke.py`
2. `python -m pytest`
3. `ruff check .`
4. `.api_connection_test/full_probe.py`
5. `python -m harness --base-url http://127.0.0.1:8080 --output reports_guidance_acceptance`
6. 通过 Codex MCP 发起活动故障筛选、故障详情、停机决策支持和目录故障会话测试。

### Contract 审查

- [x] 具体性：统一字段、六类策略、状态分支、安全边界和兼容入口均明确。
- [x] 可测试性：每项完成标准均能由 Schema、单测、黑盒探测或实机对话验证。
- [x] 完整性：覆盖设计、实现、协议元数据、业务闭环、LLM 降级、文档与部署。
- [x] 合理性：复用 MCP SDK、Pydantic、现有状态机和目录夹具，不引入新的 Agent 框架。

### Contract 确认

- [x] Generator 接受上述范围和完成标准。
- [x] Evaluator 确认标准具体、可测、完整且与现有安全边界一致。
- [x] 用户已要求检查并更新设计后直接开发部署。

Contract 创建时间：2026-08-30

Contract 完成时间：2026-08-31

Contract 状态：已完成

---

## Sprint 2A.1：DeepSeek 每日 10 元硬预算门禁

### 目标

- [x] 按北京时间自然日限制本项目 DeepSeek 调用的保守核算费用不超过 10 元。
- [x] 请求前以峰值价格、缓存全未命中和最大输出 Token 原子预占预算，防止并发超领。
- [x] 根据 DeepSeek 返回的缓存命中、缓存未命中和输出 Token 结算实际费用。
- [x] 预算不足时不请求模型，回退确定性答案，并记录 `SKIPPED/BUDGET_GATE`。
- [x] 模型请求结果不确定或缺少 usage 时将预占额按已消费处理，禁止 fail-open。
- [x] 预算与逐次用量保存到 SQLite，应用重启后继续生效。

### 文件清单

- `src/zifisense_agent_api/config.py`
- `src/zifisense_agent_api/domain/llm_models.py`
- `src/zifisense_agent_api/domain/llm_budget.py`
- `src/zifisense_agent_api/infrastructure/database.py`
- `src/zifisense_agent_api/infrastructure/llm_budget_repository.py`
- `src/zifisense_agent_api/adapters/llm/base.py`
- `src/zifisense_agent_api/adapters/llm/deepseek.py`
- `src/zifisense_agent_api/adapters/llm/budgeted.py`
- `src/zifisense_agent_api/adapters/llm/factory.py`
- `src/zifisense_agent_api/application/agent_facade.py`
- `src/zifisense_agent_api/main.py`
- `.env.example`
- `compose.yaml`
- `README.md`
- `tests/test_llm_budget.py`
- `tests/test_llm_integration.py`
- `.harness_context.md`
- `evaluation_report.md`

### Definition of Done

- [x] 默认配置为 `LLM_DAILY_BUDGET_CNY=10.00`、`LLM_BUDGET_TIMEZONE=Asia/Shanghai`、`LLM_USD_TO_CNY_RATE=7.00`。
- [x] 默认价格采用 `deepseek-v4-flash` 当前峰值：缓存命中输入 0.014、缓存未命中输入 0.44、输出 1.32 美元/百万 Token。
- [x] 金额使用 Decimal 输入和人民币微元整数持久化，不用二进制浮点记账。
- [x] 输入预估覆盖系统提示词和请求 JSON 的 UTF-8 字节上界；输出预估使用配置的 `LLM_MAX_OUTPUT_TOKENS`。
- [x] SQLite 条件更新保证 `spent + reserved + new_reservation <= daily_limit`，并发测试不得超额。
- [x] 成功响应按 usage 结算并释放差额；异常、超时或 usage 缺失按预占额核销。
- [x] 预算耗尽时底层 Provider 调用次数为 0，REST/MCP 仍返回确定性答案和 `meta.is_degraded=true`。
- [x] 预算账本包含日期、时区、Provider、模型、Token 分类、预占/结算金额、状态与时间戳。
- [x] `LLM_ENABLED=false` 时不初始化预算门禁，原有行为兼容。
- [x] Fake Provider 覆盖成功结算、预算拒绝、异常核销、跨日、跨重启和并发场景。
- [x] Ruff、完整 Pytest、三评委 Harness 和 API/MCP 全量探测通过。
- [x] 配置有效真实 Key 时，通过预算门禁执行一次显式 DeepSeek Smoke Test；失败时如实记录供应商返回，不泄露 Key。

### 验证方法

1. `python -m pytest tests/test_llm_budget.py tests/test_llm_integration.py`
2. `python -m pytest`
3. `ruff check .`
4. 三评委 Harness 与 `.api_connection_test/full_probe.py`
5. `LLM_ENABLED=true` 下执行一次真实 `agent_invoke`，核对 usage ledger 和当日预算快照

### Contract 审查

- [x] 具体性：预算口径、时区、价格、汇率、预占、结算和降级语义均明确。
- [x] 可测试性：并发、跨日、跨重启、拒绝、异常和真实调用均有验证方法。
- [x] 完整性：覆盖配置、持久化、Provider 装饰、响应语义、文档和验收。
- [x] 合理性：复用单容器 SQLite，不引入 LiteLLM/PostgreSQL；只约束本项目专用 Key 的调用。

### Contract 确认

- [x] Generator 接受上述范围和完成标准。
- [x] Evaluator 接受仅按上述标准验收。
- [x] 用户已配置项目 `.env` 中的 DeepSeek Key，并继续推进 10 元预算能力。

Contract 创建时间：2026-08-30

真实 Smoke Test 最终结果：充值并修正 Key 格式后，DeepSeek 与 Agent 均返回 HTTP 200，LLM Tool 为 `SUCCEEDED`，5 条证据引用全部有效；输入缓存未命中 711 Token、输出 991 Token，预占 22,355 微元，实际结算 11,347 微元，悬挂预占为 0。此前余额不足的 HTTP 402 与一次结构化校验失败均由确定性降级链路安全兜底，Key 未输出。

Contract 状态：已完成

---

## Sprint 2A：OpenAPI 契约修复与 DeepSeek LLM Demo 接入

### 目标

- [x] 将 `POST /api/v1/events` 的 OpenAPI 成功状态码从 202 统一为运行时实际使用的 200。
- [x] 增加默认关闭、可配置的 DeepSeek Provider；未启用时不产生任何公网模型请求。
- [x] 在安全的调查类意图中使用 DeepSeek 对确定性回答进行基于证据的中文表达增强。
- [x] 保留现有规则路由、工具执行、状态机、补测同意、审批 Challenge 和会话隔离作为最终裁决者。
- [x] DeepSeek 超时、429、5xx、空响应或无效 JSON 时返回当前确定性回答，并标记降级。
- [x] 提供 `.env`、Compose 和 README 配置说明，使用户只需设置 `DEEPSEEK_API_KEY` 即可启用。

### 范围假设

- Demo 仅向模型发送 Fixture 与脱敏结构化证据，不发送原始高频波形、API Key、审批 Challenge 或数据库记录全文。
- 首个默认模型使用 DeepSeek 当前公开的 `deepseek-v4-flash`，API Base 为 `https://api.deepseek.com`。
- 本 Sprint 只实现回答合成，不允许模型自主执行工具或写操作；受控工具规划留到 Sprint 2B。
- 比赛环境允许访问公网 API，但 CI 和默认本地测试不要求真实模型密钥。

### 文件清单

- `docs/specs/纵行科技_智能运维Agent_比赛Demo_API_v1.openapi.yaml`
- `pyproject.toml`
- `uv.lock`
- `.env.example`
- `compose.yaml`
- `README.md`
- `src/zifisense_agent_api/config.py`
- `src/zifisense_agent_api/main.py`
- `src/zifisense_agent_api/application/agent_facade.py`
- `src/zifisense_agent_api/domain/llm_models.py`
- `src/zifisense_agent_api/adapters/llm/base.py`
- `src/zifisense_agent_api/adapters/llm/deepseek.py`
- `src/zifisense_agent_api/adapters/llm/factory.py`
- `tests/test_llm_integration.py`
- `docs/LLM_INTEGRATION_PLAN.md`

### Definition of Done

- [x] OpenAPI 3.1 校验通过，`/api/v1/events` 只声明 200 成功响应，运行时测试仍返回 200。
- [x] `LLM_ENABLED=false` 时不要求 `DEEPSEEK_API_KEY`，不构造网络客户端，现有行为与响应保持兼容。
- [x] `LLM_ENABLED=true` 且缺少 DeepSeek Key 时，应用配置阶段给出不含密钥值的明确错误。
- [x] DeepSeek Adapter 使用 OpenAI-compatible Chat Completions、`https://api.deepseek.com`、JSON Output 和可配置模型。
- [x] 模型输入只包含用户问题、确定性回答、意图、任务状态和脱敏证据摘要；不包含 Challenge、Token 或原始波形。
- [x] 模型输出必须通过 Pydantic Schema；虚构 evidence ID、空响应或解析错误触发确定性降级。
- [x] `OUT_OF_SCOPE`、补测同意和工单草稿意图不调用 LLM，安全状态迁移仍由当前代码处理。
- [x] 成功调用在 `tool_executions` 中记录 Provider、模型和耗时；失败不暴露 Provider 原始异常或 API Key。
- [x] Fake Provider 单元测试覆盖成功增强、引用过滤、安全意图跳过、Provider 失败降级和禁用模式。
- [x] 完整 Pytest、Ruff、三评委 Harness 和 API/MCP 全量探测通过。
- [x] 未提供真实 Key 时，实网 DeepSeek Smoke Test 标记为“待配置”，不伪造通过结论。

### 验证方法

1. `python -m pytest tests/test_llm_integration.py`
2. `python -m pytest`
3. `ruff check .`
4. `openapi-spec-validator` 合同测试
5. 启动服务后运行三评委 Harness 与 `.api_connection_test/full_probe.py`
6. 配置真实 `DEEPSEEK_API_KEY` 后运行显式 opt-in Smoke Test

### Contract 审查

- [x] 具体性：Provider、模型、调用范围、失败语义和禁止行为均已明确。
- [x] 可测试性：每项完成标准均可由单元测试、合同测试或黑盒 Harness 验证。
- [x] 完整性：覆盖契约修复、配置、运行时接入、降级、安全、文档和验收。
- [x] 合理性：首期限制为回答合成，不在同一 Sprint 引入模型自主写工具。

### Contract 确认

- [x] Generator 接受上述目标和完成标准。
- [x] Evaluator 接受仅按上述标准验收，不增加 Contract 外要求。
- [x] 用户已明确选择 DeepSeek，并确认比赛环境允许公网模型 API。

Contract 创建时间：2026-08-30

Contract 状态：已完成
