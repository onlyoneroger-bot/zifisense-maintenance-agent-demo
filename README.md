# ZiFiSense Intelligent Maintenance Agent API

[![CI](https://github.com/onlyoneroger-bot/zifisense-maintenance-agent-demo/actions/workflows/ci.yml/badge.svg)](https://github.com/onlyoneroger-bot/zifisense-maintenance-agent-demo/actions/workflows/ci.yml)

比赛 Demo 的 REST + MCP 单容器服务。版本 1.0.0 提供真实 MCP Streamable HTTP 接入、设备与故障查询、受控多轮调查编排，以及经用户明确同意的模拟现场补测、审批工单和维修验证闭环。17 个 MCP Tool 均返回状态驱动的 `guidance`，不再停留在数据复述。DeepSeek 回答增强为可选能力；关闭、失败或预算耗尽时仍保留完整确定性处置步骤。

所有比赛目录、故障、监测、工况、维修和同线对比数据都明确标识为 Fixture。候选诊断不会被描述为最终工程结论；人工描述以 `HUMAN_CLAIM/UNVERIFIED` 保存；系统不暴露 PLC/DCS 控制工具。模型只能润色只读调查结果，引用必须对应本次返回的证据 ID，不能改变状态机、补测同意或审批结果。

## 服务与端口

只需一个容器、一个 FastAPI/Uvicorn 服务和一个 TCP 端口（默认 `8080`）：

```text
GET/POST /api/v1/...  REST API
POST     /mcp         MCP Streamable HTTP（JSON-RPC 2.0，亦支持 SSE 响应）
GET      /health      容器健康检查
```

MCP 使用官方 Python SDK 2.1.x，主协议为 `2026-07-28`，并兼容 `2025-11-25`。2026 请求是无会话模式，不需要 `Mcp-Session-Id`。

## 当前可用 REST 接口

```text
GET  /health
GET  /api/v1/capabilities
POST /api/v1/evaluation/sessions
POST /api/v1/agent/invoke
POST /api/v1/events              报警、现场补测、维修完成事件
GET  /api/v1/tasks/{task_id}
POST /api/v1/tasks/{task_id}/approvals
POST /api/v1/admin/reset
```

事件接口支持 `ALARM_RAISED`、`FIELD_MEASUREMENT_COMPLETED` 和 `WORK_ORDER_COMPLETED`。REST 契约位于 `docs/specs/纵行科技_智能运维Agent_比赛Demo_API_v1.openapi.yaml`。

## 当前可用 MCP Tools

```text
create_evaluation_session
list_assets
list_current_faults
get_fault_detail
list_fault_history
get_monitoring_summary
get_operating_context
get_maintenance_history
compare_peer_assets
ingest_alarm
request_field_measurement
ingest_field_measurement_result
draft_work_order
decide_work_order_approval
ingest_work_order_completion
agent_invoke
get_task
```

详细输入、输出和评委调用路径见 `docs/specs/纵行科技_智能运维Agent_MCP_Tools_v1.md`。`tools/list` 返回机器可读 JSON Schema、中文标题、用途说明及只读/幂等提示，是运行时权威定义。成功结果统一增加 `guidance`，包含当前阶段、紧急度、有顺序的动作、责任人、阻塞问题、升级条件和下一 Tool。

实现取舍和状态规则见 [MCP 处置引导设计](docs/MCP_GUIDANCE_DESIGN.md)。

`create_evaluation_session` 既可使用原 `scenario_id`，也可使用活动目录 `fault_id`；两者必须且只能提供一个。这样六个活动故障都能进入 `agent_invoke`、现场补测、工单审批和维修验证闭环，而 Tool 总数仍保持 17 个。

## 本地启动

Windows PowerShell：

```powershell
$env:UV_CACHE_DIR='.uv-cache'
uv sync --frozen --no-editable
.venv\Scripts\python.exe -m uvicorn zifisense_agent_api.main:app --host 127.0.0.1 --port 8080
```

通用 shell：

```bash
UV_CACHE_DIR=.uv-cache uv sync --frozen --no-editable
.venv/bin/python -m uvicorn zifisense_agent_api.main:app --host 127.0.0.1 --port 8080
```

开发默认密钥仅用于本地和 CI：`dev-evaluator-key`。部署时推荐通过 `API_CLIENTS_JSON` 配置独立账号；每个 API Key 自动映射到自己的 `client_id`，客户端仍使用标准 Bearer Token，不需要额外发送账号密码。服务端只保存 SHA-256 Hash，提交包不保存明文生产密钥。未配置账号数组时，`EVALUATOR_API_KEY_HASH` 和 `LIMITED_API_KEY_HASH` 继续作为兼容回退。

三账号配置示例（Hash 仅为格式示意）：

```dotenv
API_CLIENTS_JSON=[{"client_id":"zifisense-dev","api_key_hash":"<64位小写SHA-256>","scopes":["capability:read","evaluation:create","agent:invoke","event:write","task:read","approval:write","admin:write","mcp:use"]},{"client_id":"zifisense-ops","api_key_hash":"<64位小写SHA-256>","scopes":["capability:read","evaluation:create","agent:invoke","event:write","task:read","approval:write","mcp:use"]},{"client_id":"zifisense-review","api_key_hash":"<64位小写SHA-256>","scopes":["capability:read","evaluation:create","agent:invoke","task:read","mcp:use"]}]
```

账号数组非空时会拒绝重复账号、重复 Key Hash、非法 Hash、空 Scope 和全部禁用的配置。将某项设为 `"enabled":false` 可停用该 Key；替换其 Hash 并重启容器即可完成单账号轮换。

## 启用 DeepSeek

复制环境变量模板，并在本地 `.env` 中填写密钥：

```powershell
Copy-Item .env.example .env
```

```dotenv
LLM_ENABLED=true
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=<replace-with-real-key>
```

填写 Key 时必须替换整段尖括号占位符；真实 Key 只通过部署 Secret 注入。

应用启动时会校验配置。`LLM_ENABLED=true` 但没有 Key 会直接报告配置错误；`LLM_ENABLED=false` 时不要求 Key，也不会构造模型客户端。模型调用失败、返回空内容、无效 JSON 或引用不存在的证据 ID 时，接口仍返回原有确定性答案，并将 `meta.is_degraded` 标为 `true`。

DeepSeek 只合成安全调查答复，不开放模型自主选工具或写操作。`OUT_OF_SCOPE`、现场补测同意和工单草稿请求不会调用模型。停机类询问可获得证据化决策支持，但直接控制请求仍被拒绝。

### 每日费用上限

LLM 模式默认启用北京时间自然日 10 元预算门禁：

```dotenv
LLM_DAILY_BUDGET_CNY=10.00
LLM_BUDGET_TIMEZONE=Asia/Shanghai
LLM_USD_TO_CNY_RATE=7.00
DEEPSEEK_INPUT_CACHE_HIT_USD_PER_MILLION=0.014
DEEPSEEK_INPUT_CACHE_MISS_USD_PER_MILLION=0.44
DEEPSEEK_OUTPUT_USD_PER_MILLION=1.32
```

调用前按峰值、缓存全未命中和最大输出 Token 预占预算；成功后按 DeepSeek 返回的缓存命中、未命中和输出 Token 结算。额度不足时不会发起公网模型请求，而是返回确定性答案并记录 `SKIPPED/BUDGET_GATE`。超时或没有 usage 时按预占额核销，避免漏记账。

预算保存在当前 SQLite 数据库的 `llm_daily_budgets` 和 `llm_usage_ledger` 表中，应用重启后继续有效。要限制整个项目的费用，请使用项目专用 DeepSeek Key；其他应用直接使用同一 Key 的费用不受本服务控制。价格和汇率可能变化，部署前应根据 DeepSeek 最新价格复核上述保守配置。

## MCP 最小验证

```bash
curl -X POST http://127.0.0.1:8080/mcp \
  -H "Authorization: Bearer dev-evaluator-key" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2026-07-28" \
  -H "Mcp-Method: server/discover" \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"judge-client","version":"1.0"},"io.modelcontextprotocol/clientCapabilities":{}}}}'
```

评委平台配置：

```text
URL: http(s)://<host>:8080/mcp
Transport: Streamable HTTP
Authorization: Bearer <token>
```

## 测试

```bash
.venv/Scripts/ruff.exe check .
.venv/Scripts/python.exe -m pytest
```

自动化测试覆盖 REST 回归、双协议 MCP 探测、Bearer/Scope、17 个 Tool 的标题与 annotations、六类 Guidance、活动目录故障会话桥接、停机决策边界、三轮调查回放、人工信息门控、补测与审批闭环、REST/MCP 会话共享、10 并发调用，以及 DeepSeek 结构化输出、证据引用和失败降级。

## 三评委模拟 Harness

仓库提供不依赖 LLM 的黑盒模拟环境，分别从预测性维护业务、IT 真实性和 Agent Harness 安全角度，通过真实 REST/MCP 网络请求评分：

```powershell
.venv\Scripts\python.exe -m harness --base-url http://127.0.0.1:8080 --output reports
```

报告包含 Markdown、JSON、JUnit XML 和带哈希链的脱敏调用轨迹。Docker 一键运行、MCP Inspector 和评分规则见 [三评委模拟 Harness](docs/JUDGE_HARNESS.md)。现有三个 Profile 仍以确定性模式作为比赛安全基线；面向真实模型质量与成本的独立评测 Profile 留待后续增加。

## Docker（本地/内网）

```bash
docker build -t zifisense-agent-api:1.0.0 .
docker run --rm -p 8080:8080 zifisense-agent-api:1.0.0
```

持久化部署可使用单服务 Compose。先把账号数组作为部署 Secret 注入，再启动：

```bash
export API_CLIENTS_JSON='[{"client_id":"zifisense-dev","api_key_hash":"<sha256-of-key>","scopes":["capability:read","evaluation:create","agent:invoke","event:write","task:read","approval:write","admin:write","mcp:use"]}]'
docker compose up --build --detach
```

需要启用 DeepSeek 时，再把 `LLM_ENABLED=true` 和 `DEEPSEEK_API_KEY` 作为部署平台 Secret 注入 Compose。不要把真实 Key 写进镜像、Git 或参赛附件。

该 Compose 仅用于本地或内网，SQLite 数据保存在 `agent-data` 命名卷中。

## 公网正式部署

正式环境使用 `compose.production.yaml` 和 Caddy：只有 Caddy 对外暴露 80/443，应用的 8080 端口仅在容器网络可见；Caddy 自动申请和续期 HTTPS 证书。

```bash
cp .env.production.example .env.production
# 填写 MCP_DOMAIN、ACME_EMAIL、API_CLIENTS_JSON 等真实值
docker compose --env-file .env.production -f compose.production.yaml config
docker compose --env-file .env.production -f compose.production.yaml up --build --detach
```

用对侧将采用的官方 MCP SDK 做上线验收：

```bash
export MCP_URL="https://${MCP_DOMAIN}/mcp"
export MCP_API_KEY='<通过安全渠道取得的明文 Key>'
python scripts/mcp_sdk_smoke.py
python scripts/mcp_load_probe.py --connections 1 --concurrency 10 --requests 200
```

完整的 DNS、防火墙、Secret、证书、100 QPS 压测、回滚和发布固化步骤见 [正式部署手册](docs/PRODUCTION_DEPLOYMENT.md)。生产配置将同步调用预算限制为 25 秒，LLM Provider 单次等待 12 秒且禁用自动重试，以在对侧 30 秒超时前保留确定性降级窗口。

生产域名部署时，`MCP_ALLOWED_HOSTS` 由 `MCP_DOMAIN` 自动生成；如有浏览器来源，再单独设置 `MCP_ALLOWED_ORIGINS`。GitHub Actions 会验证 Ruff、pytest、镜像构建、非 root 用户、8080 健康检查和容器内 MCP 探测。
