# ZiFiSense Intelligent Maintenance Agent API

[![CI](https://github.com/onlyoneroger-bot/zifisense-maintenance-agent-demo/actions/workflows/ci.yml/badge.svg)](https://github.com/onlyoneroger-bot/zifisense-maintenance-agent-demo/actions/workflows/ci.yml)

比赛 Demo 的 REST + MCP 单容器服务。版本 0.2.0 在 Sprint 1 REST 基线上增加真实 MCP Streamable HTTP 接入，以及不依赖 LLM 的设备、当前故障、故障详情和历史故障查询。

所有比赛目录和故障数据都明确标识为 Fixture。候选诊断不会被描述为最终工程结论；系统不暴露 PLC/DCS 控制工具。当前 `agent_invoke` 仍是诚实降级路径，不伪造 RAG、LLM 推理、引用或审批能力。

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
```

完整 REST V1 的事件、任务查询、审批和重置接口将在后续 Sprint 开放。REST 契约位于 `docs/specs/纵行科技_智能运维Agent_比赛Demo_API_v1.openapi.yaml`。

## 当前可用 MCP Tools

```text
create_evaluation_session
list_assets
list_current_faults
get_fault_detail
list_fault_history
agent_invoke
get_task
```

详细输入、输出和评委调用路径见 `docs/specs/纵行科技_智能运维Agent_MCP_Tools_v1.md`。`tools/list` 返回机器可读 JSON Schema，是运行时权威定义。

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

开发默认密钥仅用于本地和 CI：`dev-evaluator-key`。部署前必须用真实随机密钥的 SHA-256 Hash 覆盖 `EVALUATOR_API_KEY_HASH`，提交包不保存明文生产密钥。

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

自动化测试覆盖 REST 回归、双协议 MCP 探测、Bearer/Scope、Tool Schema、查询故事线、REST/MCP 会话共享和 10 并发调用。

## Docker

```bash
docker build -t zifisense-agent-api:0.2.0 .
docker run --rm -p 8080:8080 zifisense-agent-api:0.2.0
```

生产域名部署时，把 `MCP_ALLOWED_HOSTS` 设为 JSON 数组，例如 `["agent.example.com"]`；浏览器来源同时加入 `MCP_ALLOWED_ORIGINS`。GitHub Actions 会验证 Ruff、pytest、镜像构建、非 root 用户、8080 健康检查和容器内 MCP 探测。
