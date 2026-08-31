# MCP 处置引导设计

## 设计结论

17 个 MCP Tool 不使用同一段“查完干什么”的固定文案，也不各自维护一套互不相干的规则。项目采用一个 `GuidanceEngine`：统一字段、证据边界和安全门禁，再按 Tool 类型及当前业务状态选择具体动作。

这样处理有三个直接收益：

- MCP Host 不必猜测数据背后的下一步，可以读取稳定的结构化 Guidance。
- 设备筛选、证据查询、补测、审批和维修验证各有不同处置目标，不会出现通用套话。
- DeepSeek 不可用或当日费用达到 10 元上限时，业务动作和安全边界仍然完整。

## 运行链路

```text
Tool / Agent 事实结果
        │
        ▼
GuidanceContext：Tool、严重度、诊断成熟度、证据质量、任务状态
        │
        ▼
基础安全规则：模拟声明、事实/推断分离、禁止自动控制、同意与审批门禁
        │
        ▼
六类业务策略：入口、导航、证据、现场证据、决策转换、验证编排
        │
        ▼
状态规则：CRITICAL、数据质量冲突、证据缺失、待审批、维修后验证等
        │
        ▼
GuidanceEnvelope + 确定性 Agent 行动方案
        │
        └── 可选 DeepSeek：只改写 answer，不能覆盖动作和门禁
```

## 六类策略

| 类型 | Tool | 处理重点 |
|---|---|---|
| `INTAKE` | 创建会话、接收报警 | 说明调查对象、初始状态和进入调查的方法 |
| `NAVIGATION` | 设备列表、活动故障列表 | 风险排序并选择下一调查对象，不越级给维修结论 |
| `EVIDENCE` | 详情、历史、监测、工况、维修史、同类对比 | 说明证据支持什么、不支持什么以及还缺什么 |
| `FIELD_EVIDENCE` | 申请补测、回传补测 | 处理显式同意、采集责任和 PASS/PARTIAL/FAIL 分支 |
| `DECISION_TRANSITION` | 工单草稿、审批 | 处理证据门控、影响预览、一次性 Challenge 和人工权限 |
| `VALIDATION_ORCHESTRATION` | 维修完成、任务快照、自然语言会话 | 根据任务状态选择关闭、重开、补证或审批主路径 |

## 关键状态规则

- `CRITICAL + ENGINEER_CONFIRMED + ACTION_PENDING`：先由值班工程师复核当前负荷、保护/联锁、备用机和企业 SOP，再由授权人决定检修窗口或运行限制。系统不代替停机决策。
- `MAJOR + INCONCLUSIVE + 数据质量冲突`：先查传感器安装、供电、网关和数据连续性，链路正常后再现场复测，不能先建议维修设备本体。
- `WARNING/INFO + CANDIDATE`：补齐工况和趋势；没有企业阈值及现场证据时，不建议停机或更换部件。
- 现场结果 `PASS`：只表示证据可用于人工工程判断；`PARTIAL/FAIL` 必须补齐或重测。
- 审批待处理：使用当前一次性 Challenge 做批准或拒绝，不重复签发或恢复旧 Challenge。
- 维修后改善：保存可比验证后关闭；未改善或证据不足：保留冲突并继续调查。

## 兼容设计

- Tool 名称和数量保持 17 个，原有输出字段不删除。
- 每个成功结果新增 `guidance`，旧客户端可忽略，新客户端按 `next_steps` 继续。
- `create_evaluation_session` 保留原 `scenario_id`，增加互斥的 `fault_id`，使六个活动目录故障都能进入任务闭环。
- REST `recommended_actions` 保留原三字段并增加原因、责任人、必需输入、同意/审批、阻塞状态及下一 Tool。
- MCP annotations 只是客户端提示；服务端认证、会话隔离、状态机和审批门禁仍是权威。

## 代码责任

- `domain/guidance.py`：稳定的数据契约。
- `application/guidance_engine.py`：六类策略和状态规则。
- `mcp_server.py`：Tool 描述、annotations、输入兼容和 Guidance 注入。
- `agent_facade.py`：意图路由、确定性行动方案及 DeepSeek 安全增强。
- `tests/test_guidance.py`：元数据、六类输出、目录会话桥接、停机边界和写闭环验收。
