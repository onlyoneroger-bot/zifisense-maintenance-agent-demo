# MCP 正式部署指南

## 1. 上线前条件

- 一台可被比赛平台访问的 Linux 服务器，已安装 Docker Engine 与 Compose v2。
- 一个已解析到服务器公网 IP 的域名，例如 `mcp.example.com`。
- 公网、防火墙和安全组放通 TCP 80、TCP 443；如需 HTTP/3，再放通 UDP 443。
- 正式 Bearer Key 通过独立安全渠道交付；服务器只保存 SHA-256 Hash。
- 发布前工作区必须固化到一个可追溯 Git commit 或不可变镜像 tag。

## 2. 准备正式配置

复制 `.env.production.example` 为 `.env.production`。该文件已被 Git 忽略。

必须修改：

- `MCP_DOMAIN`：正式域名，不包含协议和路径。
- `ACME_EMAIL`：证书通知邮箱。
- `API_CLIENTS_JSON`：正式账号、64 位小写 SHA-256 Key Hash 和 `mcp:use` Scope。
- 如启用 DeepSeek，设置 `LLM_ENABLED=true` 和 `DEEPSEEK_API_KEY`。

不要把明文 Bearer Key、DeepSeek Key、证书私钥或 `.env.production` 提交到 Git。

## 3. 配置检查与启动

```bash
docker compose --env-file .env.production config
docker compose --env-file .env.production build --pull
docker compose --env-file .env.production up -d
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail=100 maintenance-agent caddy
```

上述命令默认读取 `docker-compose.yml`。`compose.production.yaml` 是内容等价的兼容文件，需要显式文件名的自动化平台仍可继续使用。

Caddy 使用域名自动申请和续期证书。应用端口 8080 不映射到宿主机，只能由同一 Compose 网络中的 Caddy 访问。正式 MCP 地址为：

```text
https://<MCP_DOMAIN>/mcp
```

## 4. 正式验收

在安全终端中临时设置环境变量，不要把 Key 写入命令历史或报告：

```powershell
$env:MCP_URL = "https://mcp.example.com/mcp"
$env:MCP_API_KEY = "<通过安全渠道取得的明文 Key>"
.venv\Scripts\python.exe scripts\mcp_sdk_smoke.py
.venv\Scripts\python.exe scripts\mcp_load_probe.py --connections 1 --concurrency 10 --requests 100
```

目标硬件的 100 QPS 建议项需单独验收：

```powershell
.venv\Scripts\python.exe scripts\mcp_load_probe.py --connections 10 --concurrency 100 --requests 1000 --min-qps 100
```

验收至少包括：

1. `server/discover` 协商为 `2026-07-28`。
2. `tools/list` 返回 17 个 Tool，输入 Schema 不包含服务端 Context。
3. `list_assets` 实际调用成功且 `isError=false`。
4. 10 个并发请求全部成功，p95 小于 30 秒。
5. 错误 Key 返回 401，缺少 `mcp:use` 返回 403。
6. 两个账号的会话和任务不能交叉读取。
7. 超限返回 429 和 `Retry-After`。
8. DeepSeek 超时或失败时仍返回确定性 Guidance。

## 5. 运行边界

- 正式配置将 MCP 限流上限设为 6000 次/分钟，但这不等同于服务器已达到 100 QPS；必须以目标服务器压测为准。
- 当前持久化使用单实例 SQLite。不要直接把 `maintenance-agent` 横向扩为多个副本；多副本前应迁移到共享数据库。
- Caddy 对上游响应头等待上限为 25 秒；LLM 单次超时默认 12 秒且禁用 SDK 自动重试，以给确定性降级保留时间。
- `resources/*` 和 MCP `tasks/*` 未声明；当前 Tool 不接收文件且按同步 30 秒 SLA 设计。

## 6. 回滚

1. 为每次发布设置不可变 `AGENT_IMAGE` tag。
2. 发布前备份 `agent-data` 命名卷中的 SQLite 数据库。
3. 回滚时恢复上一个镜像 tag，并运行相同的官方 SDK Smoke Test。
4. 不删除 Caddy 数据卷；其中包含证书和 ACME 状态。

## 7. 发布前 Git 固化

当前仓库包含历史未提交改动。正式发布前应审阅 `git status --short`，提交本次代码与部署文件，并记录 commit SHA、镜像 tag、配置变更和验收报告。不要把 `.env`、`.env.production`、数据库或报告中的敏感轨迹加入提交。
