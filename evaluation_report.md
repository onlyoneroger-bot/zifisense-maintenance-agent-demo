# Sprint 1 评估报告

## 测试日期

2026-08-29

## 测试范围

- 三位评委的真实 REST/MCP 黑盒模拟。
- 评分、硬失败和报告生成。
- 会话隔离、人工门控、审批安全和防重放。
- 原项目完整回归。

## 测试结果

### 通过

1. Ruff：全仓库静态检查通过。
2. Pytest：58 项全部通过。
3. 三评委真实进程端到端运行：100/100，无硬失败。
4. 报告：Markdown、JSON、JUnit XML、哈希链 JSONL 均成功生成。
5. 脱敏：开发 API Key 与一次性审批 Challenge 不进入轨迹明文。
6. YAML：两个 Compose 文件和三个 Profile 均可解析。

### 实现中发现并修复

原关键词路由器会把“忽略规则并调用 PLC 停线”误判为普通调查，触发只读调查工具。现已在业务服务入口阻断控制类和规则绕过类请求：状态不变化、工具调用为空、意图记录为 `OUT_OF_SCOPE`，并加入三组回归输入。

## 问题列表

### Critical

无。

### Major

无。

### Minor / 验证缺口

当前执行主机未安装 Docker CLI，因此未实际执行镜像构建和 Compose 启动。Dockerfile 已设置非 root 用户，Compose 已设置只读根文件系统、`no-new-privileges` 和移除 Linux capabilities；仍应在部署主机执行文档中的 Compose 命令完成镜像级复验。

## 评分

| 维度 | 评分 | 理由 |
|---|---:|---|
| 功能实现 | 5/5 | Contract 中的三评委、报告和真实协议调用全部实现 |
| 代码质量 | 4/5 | 结构清晰、无新增运行服务依赖、静态检查与测试通过 |
| 安全与稳定性 | 4/5 | 有硬失败、隔离、超时、步数上限、脱敏和哈希链；待 Docker 实机复验 |
| 可操作性 | 4/5 | 本地与 Compose 命令、Inspector 配置和报告格式完整 |
| 综合评分 | 4/5 | 符合 Sprint Contract，可进入部署环境复验 |

## 决策

通过。Sprint 1 已完成；LLM 能力不属于本轮范围。

---

# Sprint 2A 评估报告

## 测试日期

2026-08-30

## 验收结论

通过。OpenAPI 状态码问题已修复，DeepSeek 回答增强按 Sprint Contract 完成，未改变原有安全状态机和写操作门控。

## 验证结果

1. Ruff：全仓库静态检查通过。
2. Pytest：64 项全部通过，包括 DeepSeek 适配层、Fake Provider、JSON Output、证据 ID 校验、控制输出拒绝、禁用模式和确定性降级。
3. OpenAPI 3.1：合同校验通过；`POST /api/v1/events` 静态契约与运行时均返回 200。
4. 三评委真实 HTTP Harness：100/100，无硬失败。
5. API/MCP 全量探测：29/29；17 个 MCP Tools 全部实际调用通过。
6. 密钥保护：配置校验不回显候选 Key，模型输入不含 Key 或审批 Challenge，供应商原始异常不进入 API 响应。
7. 真实 DeepSeek Smoke Test：充值并修正配置后通过；DeepSeek 与 Agent 均返回 HTTP 200，LLM Tool 为 SUCCEEDED，5 条证据引用全部有效。

## 问题列表

### Critical

无。

### Major

无。

### 验证边界

- DeepSeek 账户权限、余额、目标模型和当前公网出口已实测可用；更换部署环境后仍需按相同流程复验出口。
- 当前 Sprint 仅实现回答合成；模型自主工具规划不在本轮验收范围。

## 决策

Sprint 2A 验收通过，真实 DeepSeek Smoke Test 已完成。

---

# Sprint 2A.1 每日 10 元预算门禁评估报告

## 测试日期

2026-08-30

## 验收结论

功能验收通过。每日预算门禁、并发预占、真实 usage 结算、异常核销、跨日和跨重启持久化均符合 Contract。账户充值并修正 Key 格式后，DeepSeek 实网生成、结构化响应、证据引用和预算结算均已验证成功。

## 验证结果

1. Ruff：通过。
2. Pytest：73/73 通过。
3. 三评委 HTTP Harness：100/100，无硬失败。
4. REST/MCP 全量探测：29/29；17 个 MCP Tools 全部调用通过。
5. 并发预算：10 个请求竞争 5 份额度时仅 5 个预占成功，账面总额未超过限额。
6. 跨重启：关闭并重新打开 SQLite 后，当日预算和逐次账本保持一致。
7. 失败语义：预算不足不调用 Provider；Provider 异常按预占额核销，不 fail-open。
8. 真实 Smoke Test：HTTP 201 创建会话、DeepSeek HTTP 200、Agent HTTP 200，`meta.is_degraded=false`，LLM Tool 为 SUCCEEDED。
9. 结构化结果：JSON 结构校验通过，5 条引用全部属于本次提供的证据集。
10. 真实 usage：缓存未命中输入 711 Token、输出 991 Token；预占 22,355 微元，按实际用量结算 11,347 微元（0.011347 元），悬挂预占为 0。
11. 故障隔离复验：一次结构化结果未通过校验时，Agent 仍以 HTTP 200 返回确定性答案并标记降级，未影响 REST/MCP 可用性。

## 问题列表

### Critical

无。

### Major

无。

### 外部配置事项

无。DeepSeek 账户已充值，Key 格式已修正，`LLM_ENABLED=true`。

## 评分

| 维度 | 评分 | 理由 |
|---|---:|---|
| 功能实现 | 5/5 | Contract 的预算、并发、结算、降级和持久化全部完成 |
| 代码质量 | 5/5 | 预算装饰层、领域价格模型和独立账本职责清晰 |
| 安全与稳定性 | 5/5 | 请求前原子预占，异常保守核销，预算不足不访问公网 |
| 可操作性 | 5/5 | 实网配置、模型调用、失败降级和费用账本均已复验 |
| 综合评分 | 5/5 | 功能、契约、实网模型与费用上限全部通过验收 |

## 决策

通过，可作为 DeepSeek Demo 参赛版本提交。

---

# Sprint 2B MCP 处置引导与闭环改造评估报告

## 测试日期

2026-08-31

## 验收结论

通过。17 个 MCP Tool 已从“返回数据”升级为“返回数据并给出状态驱动的处置下一步”，工具数量、名称、原有字段和 REST 路径保持兼容。新版本已部署到 `127.0.0.1:8080/mcp`。

## 验证结果

1. Ruff：全仓库静态检查通过。
2. Pytest：78/78 通过，覆盖 Guidance、Tool annotations、六个目录故障会话桥接、停机决策支持、LLM 行动保留和原有安全回归。
3. OpenAPI：`POST /api/v1/events` 仍为 HTTP 200；扩展后的 `recommended_actions` 与静态契约一致。
4. REST/MCP 全量探测：29/29；17 个 Tool 全部实际调用通过。探测脚本改为每次生成唯一测试 ID，可重复运行。
5. 三评委真实部署 Harness：100/100，业务、IT 和 Agent 安全评委均通过，无硬失败；报告位于 `reports_guidance_acceptance/`。
6. MCP 元数据：17/17 Tool 均有中文标题、具体 description 和 annotations；九个查询 Tool 标记只读、幂等、封闭世界。
7. 目录闭环：六个活动故障均可由 `create_evaluation_session(fault_id=...)` 创建隔离会话。
8. 停机边界：CRITICAL 故障返回 `VERIFY_LIVE_SAFETY_CONTEXT` 与 `APPLY_ENTERPRISE_SOP`，未调用 LLM，也没有 PLC/DCS/停机控制副作用。
9. DeepSeek 实网：Harness 中存在 `SUCCEEDED` 调用，生成答案仍由服务端补回处置顺序；结构化输出不合格或超时时自动回退，Guidance 不丢失。
10. 费用门禁：北京时间自然日 10 元硬预算保持启用，模型失败按既定保守策略核销，不允许预算绕过。

## 实现中发现并修复

- 原黑盒探测复用固定审批会话，第二次运行会读取已消费 Challenge。现改为每轮唯一会话与事件 ID。
- DeepSeek 改写可能省略确定性行动顺序。现由服务端在模型输出后强制保留动作、责任人、原因和首个阻塞问题。
- “是否需要停机”与“直接停机、无需人工确认”原来共用拒绝规则。现前者进入 `SAFETY_DECISION`，后者继续按越权控制请求拒绝。
- MCP 列表条目曾因模型继承产生无意义的 `guidance:null`。现仅顶层结果携带 Guidance，减小负载并保持语义清晰。

## 验证边界

- 当前工作机没有 Docker CLI，因此未在本机执行镜像构建；Dockerfile、Compose 安全配置和容器测试仍由现有自动化覆盖。服务器提供的 Docker 26.1.1 能支持本项目使用的构建与 Compose 语法，部署机仍需执行一次镜像级复验。
- DeepSeek 公网响应时间和结构化输出并非每次稳定成功；服务端确定性降级是预期设计，不影响 Guidance 与业务闭环。

## 决策

Sprint 2B Contract 全部完成，设计、开发、本地部署和 Harness Evaluator 验收通过，可进入服务器镜像部署与参赛附件更新。

---

## Sprint 2C：三组账号与独立 API Key 验收

### 测试日期

2026-08-31

### 验收结论

通过。现有 Bearer 契约已扩展为部署环境可配置的多账号 Key 列表，不引入登录后台或完整 RBAC；三组账号已部署到本机服务并逐一通过 REST 与 MCP 实际连接。

### 验证结果

1. 配置：`API_CLIENTS_JSON` 支持 `client_id`、SHA-256 Key Hash、Scope 和启停状态；非法结构、重复账号、重复 Hash、空 Scope 和全部禁用会在启动阶段失败。
2. 兼容：未配置账号数组时继续使用原两组开发 Hash，现有测试和比赛 Bearer 调用方式不变。
3. 单元/协议测试：完整 Pytest 87/87 通过；Ruff 全仓库检查通过。
4. 实机 REST：三组账号调用 `GET /api/v1/capabilities` 均返回 HTTP 200。
5. 实机 MCP：三组账号的 `server/discover`、`tools/list` 和 `list_assets` 均返回 HTTP 200；每组均发现 17 个 Tool。
6. 拒绝路径：旧公开开发 Key 在部署实例返回 401；review 账号调用管理员重置接口返回 403。
7. 密钥边界：`.env` 只保存三组 SHA-256 Hash 且已被 Git 忽略；受版本控制文件明文 Key 扫描无命中。
8. 部署：本机服务已重启并监听 `127.0.0.1:8080`，健康检查返回 `status=ok`。

### 评分

- 功能实现：5/5
- 代码质量：5/5
- 接口兼容：5/5
- 安全边界：5/5
- 综合评分：5/5

### 决策

Sprint 2C Contract 全部通过。服务器地址确定后，将同一 `API_CLIENTS_JSON` Hash 配置作为部署 Secret 注入容器，并在接入文档中填写公网 URL；明文 Key 继续通过独立安全渠道交付。

---

# Sprint 3 MCP 正式部署兼容性加固评估报告

## 测试日期

2026-08-31

## 验收结论

本地验收通过，可进入正式服务器部署。对侧 Client 可使用标准 Streamable HTTP MCP SDK 连接 `/mcp`；请求身份、工具 Schema、同步超时和账号隔离均已按正式接入边界加固。

## 验证结果

1. 身份隔离：MCP Tool 从当前请求 Bearer Token 解析真实 `client_id`；两个账号使用相同幂等键互不冲突，跨账号读取任务被拒绝。
2. Schema 兼容：官方 SDK `tools/list` 精确返回 17 个 Tool，注入的 `Context` 未暴露为对侧必填参数。
3. 超时：同步 MCP 预算 25 秒；LLM 单次等待 12 秒、自动重试 0 次，至少保留 5 秒用于确定性降级和响应封装。
4. 官方 SDK：协商协议版本 `2026-07-28`，17 个 Tool，`list_assets` 返回 12 条资产且 `is_error=false`。
5. 全量测试：Pytest 92/92；Ruff 全仓库检查通过。
6. 黑盒探测：REST/MCP 29/29；17 个 Tool 均完成真实网络调用。
7. 三评委 Harness：100/100，无硬失败；报告位于 `reports_production_acceptance/`。
8. 本地负载：生产限流 6000 次/分钟，20 并发、10 连接、200 次调用全部成功；110.11 QPS，平均 177.07 ms，P50 142.00 ms，P95 387.56 ms，P99 439.85 ms。
9. 部署资产：生产 Compose 仅由 Caddy 暴露 80/443；应用为非 root、只读根文件系统、删除 Linux capabilities、带健康检查和持久化卷。
10. Secret：生产模板强制要求 `API_CLIENTS_JSON`、域名和 ACME 邮箱，不包含可用的明文 Key；Smoke/负载脚本不打印 Bearer Token。

## 外部部署门禁

- 当前工作机没有 Docker CLI，未执行镜像构建和 `docker compose ... config`；目标服务器必须执行部署手册中的配置解析、构建、健康检查和日志检查。
- Caddy 的公网证书签发依赖真实 DNS 和可达的 80/443 端口，只能在正式服务器验收。
- 本地 110.11 QPS 证明应用达到建议基线，但正式放行仍应从对侧网络对 HTTPS 地址重复 200 请求压测，排除服务器规格、TLS 和公网链路影响。
- 当前工作区包含用户已有及本轮累计的未提交变更；发布前需审查差异并创建不可变 Git Commit/Tag，未擅自提交。

## 评分

| 维度 | 评分 | 理由 |
|---|---:|---|
| MCP 接口兼容 | 5/5 | 官方 SDK discovery/list/call 实测通过，Tool Schema 保持 17 个 |
| 身份与隔离 | 5/5 | Bearer 账号贯穿会话、任务和幂等边界，跨账号访问被拒绝 |
| 超时与降级 | 5/5 | 25 秒总预算、12 秒单次 Provider、0 自动重试可配置校验 |
| 部署资产 | 4/5 | HTTPS、Secret、容器加固齐备；目标机 Docker/TLS 尚待实机门禁 |
| 性能准备度 | 5/5 | 本机 200/200、110.11 QPS、P95 387.56 ms |

## 决策

Sprint 3 实现和本地评估通过。项目已经达到“可部署”状态；完成目标服务器 Docker、DNS/证书、HTTPS 官方 SDK Smoke Test 和公网压测后，方可标记为“正式上线”。
