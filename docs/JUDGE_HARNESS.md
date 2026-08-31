# 三评委模拟 Harness

该环境以真实网络请求测试 REST API 和 MCP Streamable HTTP，不调用服务内部函数，也不使用 LLM。相同检查规则下结果可重复；运行 ID 只用于隔离持久化测试会话。

## 评委与评分

| 评委 | 权重 | 核心关注点 |
|---|---:|---|
| 预测性维护业务专家 | 40% | 设备、故障、历史、监测、工况、维修、同线对比、补测和工单闭环 |
| IT 真实性与工程专家 | 30% | 服务、鉴权、MCP 协议、Schema、幂等、错误结构和并发 |
| Agent Harness 安全专家 | 30% | 最小权限、会话隔离、越权输入、人工门控、挑战码、版本和防重放 |

综合分达到 80 分且没有安全硬失败才判定通过。Fixture 数据会一直明确标为模拟；通过报告只证明接口、状态机和证据链真实运行，不证明已连接真实工业系统。

## 本地运行

先启动目标服务，然后执行：

```powershell
.venv\Scripts\python.exe -m harness `
  --base-url http://127.0.0.1:8080 `
  --output reports
```

如需测试部署密钥：

```powershell
$env:HARNESS_API_KEY='<evaluator-key>'
$env:HARNESS_LIMITED_API_KEY='<limited-key>'
.venv\Scripts\python.exe -m harness --output reports
```

Runner 默认单请求超时 10 秒，每个 Profile 最多 50 个网络步骤。可以用 `--timeout` 调整单请求超时，但不会取消步骤上限。

## Docker Compose 运行

Harness 是一次性容器，目标服务仍只开放 `8080` 一个业务端口，Harness 不开放端口：

```bash
export EVALUATOR_API_KEY_HASH='496e7a945ef82771e7d92976c76449daa5c6899ffd0c466632846a4e302b65ca'
export LIMITED_API_KEY_HASH='e15d666e6ed2ac18a4af2bd61bebb3bb779d9c9ad1d369f0c0e18e569323adbe'
mkdir -p reports
docker compose -f compose.yaml -f compose.harness.yaml up --build --abort-on-container-exit --exit-code-from judge-harness
```

上述 Hash 对应仓库公开的本地开发密钥，只能用于 Demo。生产密钥的 Hash 仍需按主 README 设置 `EVALUATOR_API_KEY_HASH` 和 `LIMITED_API_KEY_HASH`；Harness 侧用 `HARNESS_API_KEY` 和 `HARNESS_LIMITED_API_KEY` 传入对应明文。不要把生产密钥写进 Compose 文件，并确保挂载的报告目录对容器内非 root 用户可写。

## 输出

`reports/` 包含：

- `report.md`：评委阅读报告。
- `report.json`：机器可读评分和检查明细。
- `junit.xml`：CI 测试报告。
- `trace.jsonl`：按时间追加、带 SHA-256 哈希链的请求响应证据。

轨迹会脱敏 Authorization、Token、API Key 和 `approval_challenge`。每条检查只引用 `trace:N`，可以定位到原始交换而不在摘要中复制敏感内容。

## MCP Inspector 手工验证

官方 Inspector v2 需要 Node.js 22.19 或更高版本。仓库提供只读配置：

```bash
npx @modelcontextprotocol/inspector --config harness/mcp-inspector.json
```

默认配置使用公开开发密钥，只能用于本地 Demo。远程或生产验证时应复制该配置到不纳入版本管理的位置并替换 Header。

Inspector 用于人工查看 MCP 工具目录、输入 Schema、原始请求和响应；自动判分仍由本仓库的确定性 Harness 完成。

## 当前不包含的能力

- 不调用任何 LLM API。
- 不使用模型作为裁判。
- 不做针对真实模型的 Jailbreak 或 Prompt Injection 成功率评估。
- 不宣称已连接 EAM、MES、PLC 或 DCS。

后续接入 LLM 时，应新增独立 Profile 和 Provider Adapter，不改变本轮确定性检查的判定基线。
