# 主流 Agent 任务调度价值对比

**日期：** 2026-08-10
**状态：** 外部横向评估完成；候选判断，未变更既有方案状态
**范围：** 以 Claude Code、GitHub Copilot 与 OpenAI/Codex 公开资料为样本，评估“任务理解 → 能力激活 → 执行图”对通用 nanobot 的价值、风险与边界。

## 1. 结论先行

现有方案并非在重复造主流 Agent 已有的工具循环；它补的是 nanobot 当前缺少、而主流产品已分别实现的三类能力：

1. 根据任务相关性自动选择 skill、工具或专长 agent；
2. 在隔离上下文中委派工作，并将生命周期反馈给父会话；
3. 控制上下文、模型与并行资源，而不是把全部能力和全部工作塞给主 agent。

但主流产品通常把“是否先规划”交给用户选择的 Plan Mode，或隐含在模型的 agent routing 中；没有公开证据显示它们会在**所有通用聊天场景**先做“任务对象充足性”硬校验。

因此，nanobot 的前置意图层有真实价值，但它必须是一个**窄的任务准入门**，不能演化为每轮都写长计划、反复询问批准的流程引擎。对明确、简单、无工具的回答，规划应完全跳过；对无对象或多对象的可执行请求，才应严格停止并澄清。

## 2. 横向事实对比

| 维度 | Claude Code | GitHub Copilot | OpenAI / Codex | nanobot 当前 | nanobot 候选改造 |
| --- | --- | --- | --- | --- | --- |
| 任务理解与规划 | Plan Mode 由用户切入；读取和提出计划，不编辑。 | runtime 可按用户请求与 custom agent 的描述自动推断并委派。 | 模型可从上下文理解目标；复杂任务可并行协调 subagent。 | 普通消息直接进入主模型工具循环。 | 先判定任务是否有对象/可推进前沿；只对 `ready` 任务规划。 |
| Skill 激活 | 依据 description 自动调用，正文按需入上下文。 | 根据 prompt 与 skill description 选择，选中后注入 `SKILL.md`。 | description 决定模型何时考虑 skill；skill 承载工作流。 | 默认只给目录；除 `$name` 或 `always=true` 外靠模型自行读文件。 | 基于任务产出少量候选，Planner 决定绑定；绑定后走现有全文加载。 |
| MCP / 工具 | 可限制到子 agent；依赖权限与工具集。 | 可挂到 custom agent；按 agent 范围控制。 | Skills、MCP、Tool Search 是独立能力，支持按需工具发现。 | MCP 已可注册、调用和鉴权，但不具备任务绑定语义。 | 规划为节点声明所需/优先能力；第一版不重写 ToolRegistry。 |
| Subagent | 自动选择 Explore/Plan/general-purpose 等隔离子上下文；可配置技能、工具和模型。 | 可按描述自动选择 custom agent；隔离运行，生命周期事件回父会话。 | 并行 subagent 仅适合可干净拆分的独立工作流。 | 通用 subagent 由主模型临场 spawn；结果投递约束不足。 | 用工作 DAG 决定主做/串行/并行，补精确会话与计划归属。 |
| 可见性 | 本轮官方资料未提供可直接比较的事件协议。 | 公开 subagent 生命周期事件，并支持构建 agent tree UI。 | API 提供工具、并行与可观测性能力，但本轮未以 Codex UI 作为事实依据。 | 有工具和 subagent 进度，缺 skill 选择/加载事件。 | 增加能力生命周期事件，展示简短原因和状态。 |

事实来源：[Claude Code Plan Mode](https://code.claude.com/docs/en/permission-modes)、[Claude Code Subagents](https://code.claude.com/docs/en/subagents)、[GitHub Copilot Custom Agents](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/custom-agents)、[GitHub Copilot Customization Cheat Sheet](https://docs.github.com/en/copilot/reference/customization-cheat-sheet)、[OpenAI Model Guidance](https://developers.openai.com/api/docs/guides/latest-model)、[OpenAI 插件技能文档](https://developers.openai.com/plugins/build/skills)。

## 3. 对既有方案的重新评估

### 3.1 方案与主流一致的部分

- **能力不应只是目录。** Claude、Copilot 和 OpenAI 的技能资料均采用“可发现描述 + 相关时加载的完整工作流”。nanobot 的 Capability Candidate/Binding 正是在补这个缺口。
- **subagent 的核心价值是上下文隔离，而不只是并行。** Claude 明确把高噪声探索留在独立上下文；Copilot 也将子 agent 作为隔离的任务执行单元。nanobot 的“只给子任务最小输入、结果回传摘要”是正确方向。
- **并行只适用于独立工作。** OpenAI 对并行 subagent 的公开说明同样限定在可干净分解的工作流；这支持已确定的 DAG、依赖和写入范围要求。
- **运行事件是必要能力。** Copilot 已把子 agent 生命周期事件作为父会话流的一部分。nanobot 将 skill/MCP 的选择和加载也做成事件，是合理补齐，不只是 UI 装饰。

### 3.2 nanobot 必须比主流代码 Agent 更严格的部分

Claude Code 与 Copilot 的主要工作对象通常是当前代码仓库；即便用户表达简略，工作目录、打开文件和 diff 也提供了天然对象。nanobot 是跨渠道、通用任务 Agent，用户可能只说“处理一下”。在没有可指向对象时，默认探索网络、文件、记忆或 spawn 都没有正当任务边界。

因此，FR-003/FR-004 的“无对象或多无关对象时只澄清”不是为了模仿 Plan Mode，而是 nanobot 作为通用 Agent 的必要安全与体验边界。

### 3.3 不应照搬的部分

- **不引入用户审批式 Plan Mode。** Claude 的 Plan Mode 是代码修改前的产品交互选择；nanobot 已确认：任务明确且既有权限允许时应直接执行，不能每次再让用户批准计划。
- **不预置固定角色池作为调度主轴。** Claude/Copilot 的专长 agent 适合代码领域；nanobot 的通用任务不应硬塞到 `researcher`、`writer` 等固定人设。工作 DAG 的节点定义比角色名更通用。
- **不在第一版动态收缩/重写工具注册。** OpenAI 的 Tool Search 与 Copilot 的 agent-scope 工具说明了长期方向，但改变 nanobot ToolRegistry 的可见性会影响现有 Runner 行为。V1 只增加“计划已绑定能力”的上下文与审计，保留既有工具集和权限链。
- **不让自动选择越过权限。** 外部产品也将 skill、工具、权限分层；nanobot 不应因命中 skill/MCP 改写账号、策略或确认机制。

## 4. 价值是否覆盖新增代价

| 任务形态 | 预期净价值 | 原因 | 必须避免的代价 |
| --- | --- | --- | --- |
| 自包含问答 | 低 | 几乎不需要技能、工具或拆分。 | 不进入 Planner；避免为一句回答多次模型调用。 |
| 单一步骤且对象明确 | 中 | 可稳定选中适用 skill/MCP，减少用户记忆命令。 | 不为此 spawn；计划输出应退化为单父节点。 |
| 多步骤专业工作流 | 高 | skill 可提供稳定步骤、模板和验收；MCP 提供受控动作。 | 防止误选无关流程与上下文膨胀。 |
| 多对象且可并行 | 很高 | DAG 可隔离上下文、缩短墙钟时间、降低主 agent 负担。 | 仅在输入、写入范围和验收可拆分时并行。 |
| 无对象/多无关对象 | 很高（风险降低） | 防止无边界探索和错误推进。 | 澄清必须只有一个聚焦问题，不能借澄清之名空转。 |
| 跨轮续办 | 高 | TaskFrame、PlanReceipt 和延后结果能减少重复说明与遗漏。 | 不能污染 memory、provider state 或其他会话。 |

实际收益不能以“加载了多少 skill”或“spawn 了多少 subagent”衡量。正确指标是任务成功率、用户纠正/重复说明次数、有效能力使用率、端到端成本、P95 延迟、主 agent 上下文增长，以及跨会话错误数（必须为零）。

## 5. 风险判断与收敛建议

### 必须接受并测量的成本

- 普通自然语言回合会增加一次受限意图判断；可推进任务还会增加一次无工具规划调用。
- 候选描述、计划约束和已绑定 skill 会增加输入 token；subagent 会增加模型 token 与并发占用。
- 复杂任务的最终答复可能等待必要节点汇合，首 token 和最终完成时间都可能变慢。

OpenAI 官方建议保持提示词和工具集精简，并只暴露任务相关工具；其并行说明也仅承诺对独立工作流降低墙钟时间，而不承诺降低总成本。[OpenAI Model Guidance](https://developers.openai.com/api/docs/guides/latest-model)

### 不可接受的风险

1. feature flag 关闭仍出现额外模型调用、状态写入或工具行为；
2. skill/MCP 候选在无对象或歧义回合触发业务行为；
3. 命中能力后改变既有权限、确认或安全策略；
4. 子任务结果跨有效 session key 或跨 `plan_id` 回注；
5. 计划未完成却向用户提交“已完成”终答。

### 候选收敛结论

保留“任务准入 → 能力候选 → 执行图 → 原 Runner”的方向，但把能力候选视为 **ExecutionPlanner 的输入**，而非新的一次 LLM 回合或另一个常驻调度服务：

```text
restore / compact / command
  → IntentRecognizer
  → clarify | reply | ready
  → ready 时本地检索 Capability Candidates
  → 一次 ExecutionPlanner：节点、依赖、执行者、能力绑定
  → 原 Context / ToolRegistry / Runner
```

这使 nanobot 获得主流产品的“按需能力激活”与“隔离委派”优点，同时保留面向通用聊天的对象准入优势。它不是要让每个回合都变成 Claude 的 Plan Mode。

## 6. 本次验证留痕

- 本体：检验新增两层是否属于真实架构缺口，还是重复造轮子。
- 已核验：Claude 的自动子 agent、隔离上下文与 Plan Mode；Copilot 的意图匹配、自动委派、父会话事件；OpenAI 对相关工具暴露、并行独立性和成本/延迟权衡的说明。
- 高风险反证：未找到公开证据支持“所有聊天消息都应先做重规划”；因此建议限定 Planner 的进入条件。
- 未做产品试用：本轮仅使用官方公开资料与 nanobot 已取证源码，不对第三方产品行为做未证实推断。
