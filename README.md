# ZiFiSense Intelligent Maintenance Agent API

[![CI](https://github.com/onlyoneroger-bot/zifisense-maintenance-agent-demo/actions/workflows/ci.yml/badge.svg)](https://github.com/onlyoneroger-bot/zifisense-maintenance-agent-demo/actions/workflows/ci.yml)

比赛 Demo API 的 Sprint 1 可调用基线。本版本真实运行认证、Scope、限流、幂等、SQLite 会话隔离和报警 Fixture 持久化；Agent 调用明确处于降级模式，不伪造 RAG、工具调用、事件或审批能力。

## 当前可用接口

```text
GET  /health
GET  /api/v1/capabilities
POST /api/v1/evaluation/sessions
POST /api/v1/agent/invoke
```

完整 REST V1 的事件、任务查询、审批和重置接口将在后续 Sprint 开放。REST 接口契约位于 `docs/specs/纵行科技_智能运维Agent_比赛Demo_API_v1.openapi.yaml`。

## MCP 状态

当前代码尚未注册 `/mcp`，不得把本仓库描述为已经完成 MCP 接入。下一阶段将保留现有 REST API，在同一 FastAPI 容器增加 MCP Streamable HTTP Transport，并实现设备、当前故障、故障详情和历史故障查询。

研发规格索引见 `docs/README.md`。

## 本地启动

Windows PowerShell：

```powershell
uv sync --frozen --no-editable
.venv\Scripts\python.exe -m uvicorn zifisense_agent_api.main:app --host 127.0.0.1 --port 8080
```

通用 shell：

```bash
uv sync --frozen --no-editable
.venv/bin/python -m uvicorn zifisense_agent_api.main:app --host 127.0.0.1 --port 8080
```

开发默认密钥仅供本地测试：`dev-evaluator-key`。部署前必须用真实随机密钥的 SHA-256 Hash 覆盖 `EVALUATOR_API_KEY_HASH`，提交包不保存明文密钥。

生成 Hash：

```powershell
python -c "import hashlib; print(hashlib.sha256('replace-me'.encode()).hexdigest())"
```

## 最小验证

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/api/v1/capabilities \
  -H "Authorization: Bearer dev-evaluator-key"
curl -X POST http://127.0.0.1:8080/api/v1/evaluation/sessions \
  -H "Authorization: Bearer dev-evaluator-key" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: local-eval-001" \
  -d '{"scenario_id":"reducer_gear_alarm_v1","locale":"zh-CN"}'
```

创建会话后，把响应中的三个标识带入 Agent 请求：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/agent/invoke \
  -H "Authorization: Bearer dev-evaluator-key" \
  -H "Content-Type: application/json" \
  -d '{
    "evaluation_session_id":"<EVAL_ID>",
    "conversation_id":"<CONV_ID>",
    "task_id":"<TASK_ID>",
    "message":"当前设备发生了什么？",
    "locale":"zh-CN"
  }'
```

Sprint 1 Agent 响应应满足：`meta.is_degraded=true`，引用、工具执行和 Agent 推断为空，任务仍为 `ALARM_RECEIVED`。

## 测试

```bash
.venv/Scripts/ruff.exe check .
.venv/Scripts/python.exe -m pytest
```

## Docker

```bash
docker build -t zifisense-agent-api:0.1.0 .
docker run --rm -p 8080:8080 zifisense-agent-api:0.1.0
```

当前开发工作机没有 Docker CLI，Dockerfile 已纳入静态检查，但必须在具有 Docker 的环境完成镜像构建、非 root 运行和健康检查后，才能声明发布就绪。

GitHub Actions 会在每次推送和 Pull Request 中运行 Ruff、pytest 和 Docker build，作为本机验证的补充。
