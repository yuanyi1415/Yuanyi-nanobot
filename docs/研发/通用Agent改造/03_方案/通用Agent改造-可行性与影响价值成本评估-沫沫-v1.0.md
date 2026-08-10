# 通用 Agent 改造 — 可行性与影响/价值/成本评估（评审输入）

> ✍️ **作者/维护：沫沫（MoMo）**｜AI 搭档执行产物，非 Codex 设计图纸；内容与 Codex 设计冲突时以上位文档为准

**版本：** v1.0
**性质：** 评审输入稿（针对《轻量优先执行规划技术设计 v0.1》《模型输入输出契约 v0.1》的独立评估）
**日期：** 2026-08-10
**评估基准：** [ADR-009：轻量优先三车道改造基准](../06_决策记录/ADR-009-轻量优先三车道改造基准.md)、[意图理解与调度需求 v0.8](../01_需求/意图理解与调度需求.md)
**方法：** 架构 skill（codebase-evaluation / codebase-architecture-analysis）+ 产品 skill（product-pm-skills）+ 代码取证（两个并行取证任务实读 nanobot 源码，证据均附文件:行号）

---

## 0. 结论摘要

1. **设计方向正确**：把"LLM 临场决定"换成"机器准入 + 受控规划"是本质正确的方向；ADR-009 的轻量优先基准是这份设计最值钱的决定（快速车道零新增模型调用）。
2. **可行性分档**：AdmissionGate ✅ 可行；Skill 自动绑定 🟡 有条件可行；Planner DAG + 执行计划协调器 ❌ 现状下不可行（三处硬约束）；RouteReceipt 校验 🟡 有条件可行。
3. **价值分主次**：skill 自动绑定（每天高频）> 准入澄清（中频）> 编排车道（低频但价值最高）。
4. **成本前轻后重**：切片 1-3 约 1~1.5 周；切片 4-5（编排车道）保守 2~3 周且需先解决三个文档盲区。
5. **建议**：按"小核心先做出来实践验证再扩展"走——先切片 1+2（观测 + skill 引导），编排车道后置且以最小形态落地，不做完整 DAG 引擎。

---

## 1. 可行性评估

### 1.1 AdmissionGate / IntentResolver — ✅ 可行（低风险）

- 主消息链路为固定 7 stage：`restore → compact → command → build → run → save → respond`（`nanobot/agent/loop.py:1522-1530`），command 命中即短路返回（`loop.py:1638-1685`），普通消息从 build 组装、run 进入模型调用。
- 在 command 与 build 之间插入确定性准入 stage 是干净改法。
- **注意**：插点时 `ctx.runtime` 尚未解析（`_build_turn` 内才 `runtime_for_session`，`loop.py:1690-1692`）、history/initial_messages 未构建。若 gate 需要模型判断，需放在 `_build_turn` 内做"预飞"检查，或接受 gate 仅用确定性规则。

### 1.2 Skill 自动候选 + 命中注入 — 🟡 有条件可行

- 现状：skill 只有三条可见路径——`always=true` 全文注入、`$skill` 显式引用全文注入（合为 `# Active Skills`，`context.py:100-113`）、其余仅以"名称—描述+路径"目录摘要进 system prompt（`skills.py:128-172`）。
- **无 activation 概念、无 SkillDescriptor 类**（只有 dict，`skills.py:50`）；`active_skill_names` 唯一来源是消息文本里的 `$skill`（`context.py:228-232`），**没有外部注入通道**。
- 前提条件：给 ContextBuilder 增加外部 `active_skill_names` 注入通道，并定义与 `always`/`$skill`/`disabled` 的合并优先级，否则既有语义漂移。

### 1.3 Planner DAG + 执行计划协调器 — ❌ 现状下不可行

三处硬约束（实施前必须验证）：

1. **provider 无 JSON-only 结构化输出**：`chat()`/`chat_with_retry()` 签名无 `response_format`/schema 参数（`providers/base.py:504-513, 780-792, 916-928`）；全仓 `response_format` 仅出现在图像生成。结构化输出只能走 `tools=[] + prompt 约束 + json_repair 解析`（容错底座存在，`base.py:145`），或改 provider 抽象层（横向改动大）。
2. **runner 单循环无 DAG/任务队列概念**：`AgentRunSpec` 工具固定（`runner.py:922, 1068-1098`），无任务队列/DAG 执行器。
3. **无"不落历史的一次性指令"通道**：Runtime Context 附加到当前 user 消息内容并**持久化回放**（`runtime_context.py:120-145`，`loop.py:708-714`）；现有唯一"不落历史"窄通道是 `_command=True` 消息（`session/manager.py:244`）。

### 1.4 RouteReceipt 结果校验 — 🟡 有条件可行

- 有利条件：结果链路单一清晰——`subagent.py:552-568` 构造 `InboundMessage(channel=system, session_key_override=父会话key, metadata={subagent_task_id,...})` → `loop.py:1197/1227` 两条消费路径；key 隔离天然防跨会话串扰（A 会话任务不会进 B 会话）。
- 前提条件：
  1. 现有标识只有 8 位短 uuid + session_key_override，**无 plan_id 概念**，需新增并全链路透传（spawn → 运行登记 → announce → loop 消费）；
  2. 现有路由是**信任链不是校验链**：`_announce_result` 与 `run()` 都不验证"该 task 是否由该会话发起"，`SubagentManager.spawn` 是公开方法可被 cron/automation 绕过工具直调——需在 manager 层加派发闸；
  3. 同一结果存在 mid-turn 注入（`loop.py:1197-1224`）与独立 dispatch（`loop.py:1227`）**双消费路径，无原子性**，去重只靠同 session task_id 检查（`loop.py:2073-2077`）——单次消费需引入消费状态存储。

---

## 2. 落地影响面

### 2.1 改动范围（按切片由小到大）

| 切片 | 改动文件 | 影响 |
|---|---|---|
| 1 零侵入观测 | 新增日志模块 | 零行为影响 |
| 2 skill 引导 | `skills.py` + `context.py`（接口级） | 有回归面：`$skill`/`always`/`disabled` 语义不能漂移 |
| 3 准入澄清 | `loop.py` 插点 + no-run 收尾 | 影响 command 短路边界、会话收尾 |
| 4-5 编排 | `subagent.py` + `spawn.py` + `session/manager.py` + **provider 抽象层** | 横向改动最大 |

### 2.2 设计文档未覆盖的风险点（取证发现）

1. **unified 会话模式**：所有渠道共享一份 `Session.metadata`（`loop.py:811`），计划状态放 metadata 会串扰——设计未提，需按 plan_id 嵌套隔离。
2. **spawn 闸必须在 manager 层**：`SubagentManager.spawn` 是公开方法，工具层挡不住 cron/automation 直调。
3. **结果消费双路径无单一出口**：注入 + 独立派发两条路径都要过校验，去重逻辑跨 session/重启后无消费记账。
4. **short uuid 升格**：8 位 task_id 做 RouteReceipt 需改为全局唯一并透传。

---

## 3. 价值评估

### 3.1 痛点证据链（真实、有实锤）

- 2026-08-10 两次提醒：任务太大该拆 rx、新项目该用 pm/架构 skill；
- 2026-08-07："全部都是你去做效果一定很差"（派 subagent 指令）；
- 2026-08-09："能真正并行才并行派发"；
- 决策卡片 #038（2026-08-10 入卡）："主动性是机制责任"——用户不该当提醒器。

### 3.2 价值分层

| 能力 | 价值 | 发生频率 |
|---|---|---|
| Skill 自动绑定（切片 2） | 直接命中"该用的 skill 没用上"日常痛点 | **每天高频** |
| 准入澄清（切片 3） | 防无对象乱探索/多候选擅自选择 | 中频 |
| 编排车道（切片 4-5） | 复杂任务机器管控、结果防串扰 | **低频**（nanobot 内部多目标并行场景少） |

### 3.3 必须点破的对齐问题

用户 2026-08-10 的两个痛点（主动用 skill、主动拆 RX 任务）中，**RX 拆活走的是 agent-task-dispatch skill 与外部派发，不经过 nanobot 内部 subagent 机制**。本改造能解决"沫沫主动用 skill"（切片 2），但"主动拆 RX"的解法在沫沫的派发 skill 层，不在内核改造里。两条线需分清，不要把内核改造当成解决一切的药。

---

## 4. 成本评估

### 4.1 运行时成本 — ✅ 显性可控（设计最大亮点）

ADR-009 三车道保证：快速车道零新增模型调用、零编排状态；新增 4 类结构化调用（Admission/SkillSelection/Plan/PlanJoin）只在消歧、多候选、编排合龙时触发（契约 §9 车道与模型调用矩阵）。正常问答不交税。

### 4.2 开发成本 — ⚠️ 前轻后重

- 切片 1-3：约 1~1.5 周（含回归）；
- 切片 4-5：保守 2~3 周（provider 结构化输出改造 + runner 扩展 + 结果路由重做 + 三个文档盲区处理）。

### 4.3 维护成本

新增约 5 个模块（admission/skill_selection/orchestration/result_router/plan_coordinator）+ 4 类契约 + 状态机；feature flag 双轨长期并存，需持续跟进。

---

## 5. 建议实施路径

按用户既定原则"小核心先做出来实践验证再扩展"（2026-08-09 复盘）：

1. **切片 1+2（观测 + skill 引导车道）先行**：价值/成本比最高，直接命中每天发生的痛点；feature flag 关闭零影响，可灰度。
2. **切片 3（准入澄清）随后**：防乱探索（实测案例：2026-08-10 ef05880c 会话出现过路径写错双重 triggers/triggers 的乱探索）。
3. **编排车道（4-5）后置**：以"复用现有 subagent 的最小形态"（带 plan_id 的受控 spawn）落地，**不做完整 DAG 引擎**；先用事实回放证明收益，再决定是否重做 runner。
4. **风险对冲**：实施前先做契约 §10 的三个验证（provider JSON-only 兼容性、Admission 误拦率、skill 误绑率），任一不过则对应切片停手。

---

## 6. 验证记录

- **本体**：评估"意图理解与执行规划"改造在 nanobot 现有代码上的可行性与成本价值。
- **高风险点**：插点可行性、skill 注入通道、provider 结构化输出、结果路由归属、成本是否失控。
- **逐点验证**：两个并行取证任务实读源码（loop.py/skills.py/context.py/runtime_context.py/providers/base.py/subagent.py/spawn.py/runner.py/session/manager.py），结论均附文件:行号证据（见第 1 节）。
- **实测**：无（本评估为静态取证；未跑真实回放——这是实施前必须补的验证，对应契约 §10）。
- **未验证项**：provider JSON-only 兼容性未实测；unified 模式下 metadata 串扰未做实验；中文 skill 召回质量未测。均已在正文标注为实施前验证项。

---

## 7. 文档地位

本文件是独立评估输入，不改变 Codex 产出文档的状态与决策效力；内容与设计文档冲突时，以 ADR-009 与需求 v0.8 为准，本文件仅提供实施建议。
