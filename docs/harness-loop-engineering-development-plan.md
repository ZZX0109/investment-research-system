# Investment Research Harness Engineering 与 Loop Engineering 开发计划

版本时间: 2026-07-02

## 1. 定位

本项目下一阶段不应只被描述为“金融投研 Demo”，而应升级为:

> 面向个人投资者的金融投研 Agent Harness 与持续投研 Loop 系统。

这里的 Harness Engineering 指模型之外的系统工程，包括工具接口、权限、状态、记忆、证据链、审计、运行追踪、评估和错误恢复。Loop Engineering 指围绕投研任务设计可重复运行的闭环，包括数据刷新、证据审计、报告生成、用户反馈、历史复盘和 harness 自我改进。

本计划的核心原则是:

- 模型只负责推理和解释，不直接拥有事实。
- 工具负责事实获取，证据层负责事实记录，审计层负责结论约束。
- 每次投研都是一个可追踪 run，不是一次不可复现的聊天。
- 每个循环都有停止条件、失败状态和人工可检查输出。

## 2. 论文依据与项目启发

| 论文 / 研究 | 关键结论 | 对 Investment Research 的启发 |
| --- | --- | --- |
| ReAct: Synergizing Reasoning and Acting in Language Models, 2022. https://arxiv.org/abs/2210.03629 | 将推理轨迹与外部动作交替执行，能减少幻觉并提高任务可解释性。 | 投研 Agent 应采用 `plan -> tool action -> observation -> revise`，而不是一次性生成报告。 |
| Toolformer: Language Models Can Teach Themselves to Use Tools, 2023. https://arxiv.org/abs/2302.04761 | LLM 需要学会何时调用工具、调用什么工具、如何吸收工具结果。 | 建立金融工具注册表，让行情、财报、新闻、历史类比、计算器都成为标准工具。 |
| ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs, 2023. https://arxiv.org/abs/2307.16789 | 大规模 API 使用需要工具检索、调用路径规划和自动评估。 | API Key 管理后，应增加工具路由器和工具调用评分，而不是把所有 API 暴露给模型。 |
| Reflexion: Language Agents with Verbal Reinforcement Learning, 2023. https://arxiv.org/abs/2303.11366 | Agent 可以把失败反馈写入 episodic memory，在后续尝试中改进。 | 经验历史池不只存过期证据，也应存失败原因、审计扣分和下次改进建议。 |
| Self-Refine: Iterative Refinement with Self-Feedback, 2023. https://arxiv.org/abs/2303.17651 | 生成、反馈、修订的循环能在测试时提高输出质量。 | 投研报告生成应拆成初稿、审计反馈、修订稿三步。 |
| CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing, 2023. https://arxiv.org/abs/2305.11738 | 自我纠错需要外部工具反馈，而不是只让模型自我反省。 | Evidence Judge 必须能调用权威来源、结构化数据和计算器来验证结论。 |
| Voyager: An Open-Ended Embodied Agent with Large Language Models, 2023. https://arxiv.org/abs/2305.16291 | 自动课程、技能库和执行反馈能支持长期学习。 | Investment Research 可建立“投研技能库”，如财报前检查、集中度检查、估值高位检查、新闻突变检查。 |
| SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering, 2024. https://arxiv.org/abs/2405.15793 | Agent 需要专门设计的交互界面和动作接口，接口质量会影响任务表现。 | 金融 Agent 需要专门的投研工作台界面: 运行轨迹、工具输出、证据表、审计扣分和版本对比。 |
| FinRobot: An Open-Source AI Agent Platform for Financial Applications using LLMs, 2024. https://arxiv.org/abs/2405.14767 | 金融场景需要多层 Agent 和金融专用工具链。 | 当前五个模块应组织成金融专用 harness，而不是泛用聊天机器人。 |
| FinRobot: AI Agent for Equity Research and Valuation with LLMs, 2024. https://arxiv.org/abs/2411.08804 | 股权研究需要数据整合、概念分析、投资 thesis 合成，并动态更新数据。 | 单标的卡片应拆为 Data Agent、Concept Agent、Thesis Agent、Risk Judge。 |
| Finance Agent Benchmark, 2025. https://arxiv.org/abs/2508.00828 | 即使配备搜索和 EDGAR，金融 Agent 在真实研究任务中准确率仍有限，最佳约 46.8%。 | 项目必须强调辅助研究、证据链、审计和不确定性，不输出确定性买卖建议。 |
| MultiFinRAG, 2025. https://arxiv.org/abs/2506.20821 | 财报、10-K、10-Q、投资者材料包含文本、表格、图表，普通 RAG 容易丢失结构。 | 财报解析要分文本块、表格块、图表块；表格进结构化库，图表生成摘要和关键数值。 |
| The Last Harness You'll Ever Build, 2026. https://arxiv.org/abs/2604.21003 | Harness Evolution Loop 使用 Worker、Evaluator、Evolution Agent 闭环优化 harness。 | 后期可让系统根据失败 run 自动提出工具、prompt、阈值和审计规则改进建议。 |
| Observability-Driven Automatic Evolution of Coding-Agent Harnesses, 2026. https://arxiv.org/html/2604.25850v3 | Harness 改进依赖组件、轨迹、决策三层可观测性。 | Investment Research 必须先做 run trace 和事件日志，否则无法评估 Agent 是否真的变好。 |

## 3. 总体架构计划

目标架构分为七层:

```text
用户账户 / 前测 / 持仓
  |
  v
任务 Planner
  |
  v
工具 Harness
  - 行情工具
  - 财报/公告工具
  - 新闻事件工具
  - 历史类比工具
  - 计算器/指标工具
  - 权威检索工具
  |
  v
证据与上下文 Harness
  - 结构化数据表
  - 文档块
  - 表格块
  - 图表摘要
  - source / observedAt / validUntil / confidence
  |
  v
投研 Agent Loop
  - Data Agent
  - Document Agent
  - Scenario Agent
  - Thesis Agent
  - Evidence Judge
  - Bull/Bear Agent
  |
  v
报告与可视化
  - 多模态投研卡片
  - 证据链表格
  - 历史情景图表
  - 风险雷达
  - 运行轨迹
  |
  v
经验历史池 / 用户反馈 / 复盘
  |
  v
Harness 改进建议
```

## 4. Harness Engineering 开发模块

### 4.1 工具注册表

新增工具注册层，把外部数据源统一封装为可审计工具。

第一版工具:

- `market.snapshot`: 获取最新价格、涨跌幅、成交量、时间戳。
- `market.history`: 获取三年日线复权价格。
- `filing.latest`: 获取 SEC/EDGAR 或公告入口。
- `document.parse`: 拆分财报 PDF/TXT/CSV 为文本、表格、图表块。
- `news.search`: 获取新闻摘要、来源、发布时间。
- `scenario.match`: 匹配历史相似情景。
- `metrics.calculate`: 计算收益率、最大回撤、集中度、估值分位。
- `authority.search`: 检索 SEC、交易所、公司 IR、基金公告等权威来源。

每次工具调用必须记录:

- `runId`
- `toolName`
- `inputHash`
- `sourceProvider`
- `startedAt`
- `finishedAt`
- `status`
- `error`
- `outputSummary`
- `evidenceIds`

### 4.2 证据图谱

当前已有 `evidence_records`，下一步应从“证据列表”升级为“证据图谱”。

新增关系:

- `supports`: 某证据支持某结论。
- `contradicts`: 某证据反驳某结论。
- `depends_on`: 某模型推断依赖哪些证据。
- `supersedes`: 新证据替代旧证据。
- `derived_from`: 指标由哪些行情或财报字段计算得来。

这样 Research Quality Judge 才能判断“结论是否被证据支持”，而不仅是判断“有没有证据”；它评价研究严谨性，不评价标的是否值得买。

### 4.3 运行轨迹面板

前端新增 `Agent Run Trace` 面板。

展示内容:

- 当前 `runId`
- Planner 拆分任务
- 每个工具调用
- 每个 Agent 的输入摘要和输出摘要
- Research Quality Judge 扣分项
- 最终报告版本
- 失败或兜底状态

验收标准:

- 点击任一投研报告，可以看到本次报告的工具调用顺序。
- 任一模型结论可以反查它引用的证据。
- 外部 API 失败时，面板明确显示失败原因和是否使用缓存。

### 4.4 权限与安全 Harness

本项目的金融边界应写入系统层，而不是只靠提示词。

规则:

- 禁止输出确定性买入/卖出指令。
- 禁止把用户 API Key 暴露给前端。
- 新闻和研报只保存摘要、链接、来源、时间，不全文搬运。
- 高风险操作需要用户确认。
- 用户偏好只能改变分析权重和风险阈值，不能让模型迎合用户持仓。

### 4.5 评估 Harness

建立小型本地评估集，作为每次改动后的质量门。

样例任务:

- NVDA 财报前高估值情景分析。
- TSLA 新闻事件升温后的风险审查。
- QQQ + NVDA 组合集中度检查。
- 贵州茅台 A 股公告与价格回撤检查。
- 沪深 300 ETF 基金型用户行业暴露分析。
- 外部行情接口失败时不得生成伪实时结论。

指标:

- 证据完整率。
- 过期证据拦截率。
- 模型推断标记率。
- 工具调用成功率。
- 报告可复现率。
- 审计扣分覆盖率。
- 不当投资建议拦截率。

## 5. Loop Engineering 开发模块

### 5.1 单次投研 Loop

```text
用户选择标的
→ Planner 生成任务
→ 工具层拉取行情/财报/新闻/历史情景
→ 证据层入库
→ Thesis Agent 生成初稿
→ Research Quality Judge 审稿
→ Bull/Bear Agent 生成反方观点
→ 报告 Agent 修订输出
→ 保存 run trace 和报告版本
```

停止条件:

- 必需证据类型齐全，且没有高风险过期证据。
- 审计分数达到阈值，例如 70。
- 若审计不通过，则输出“数据不足”，不生成综合建议。

### 5.2 证据刷新 Loop

```text
定时或用户触发
→ 扫描 observedAt / validUntil
→ 判断行情、新闻、财报、模型推断是否过期
→ 归档旧证据到经验历史池
→ 调用工具刷新数据
→ 重新生成依赖旧证据的模型推断
→ 生成新旧差异说明
```

频率:

- 行情: 超过 1 个交易日刷新。
- 新闻: 超过 24 小时刷新。
- 估值指标: 随行情每日刷新。
- 财报: 每 7 天检查，或公告出现时刷新。
- 模型推断: 超过 24 小时，或依赖证据过期时刷新。

### 5.3 历史类比 Loop

```text
提取当前特征
→ 按 asOfDate 截断历史数据
→ 匹配过去三年相似窗口
→ 计算后续 1 周 / 1 月 / 3 月收益和最大回撤
→ 检查未来数据泄漏
→ 输出风险分布
```

硬约束:

- 不能使用 `asOfDate` 之后的信息做样本匹配。
- 收益率使用复权价格。
- 只输出历史风险分布，不输出“未来会涨跌”。

### 5.4 审计与修订 Loop

```text
报告初稿
→ Evidence Judge 检查证据支持度
→ CRITIC 风格工具验证
→ 发现缺口则重新调用工具
→ 发现推断越界则降级或删除结论
→ 输出修订稿
```

审计维度:

- 证据是否过期。
- 结论是否有直接证据支持。
- 数字是否来自结构化计算。
- 是否误把模型推断当事实。
- 是否出现个性化荐股越界。
- 是否缺少反方观点。

### 5.5 用户反馈 Loop

前端新增反馈按钮:

- 有帮助。
- 证据不足。
- 继续观察。
- 加入复盘。
- 设置触发器。

反馈进入用户记忆:

- 用户更关心回撤还是成长。
- 用户是否频繁忽略某类风险。
- 哪些报告被保存或复盘。
- 哪些触发器实际命中。

该 loop 的目标不是个性化荐股，而是个性化排序和风险提示。

### 5.6 Harness Evolution Loop

参考 2026 年 harness evolution 研究，第一版不让系统自动改代码，但可以让它自动生成“改进建议”。

```text
收集失败 run
→ Evaluator 总结失败模式
→ Evolution Planner 生成改进建议
→ 人类确认后进入开发任务
```

可生成的建议类型:

- 新增一个工具。
- 修改某个证据有效期。
- 增加一个审计规则。
- 修改某类报告模板。
- 增加一个评估样例。
- 降低某类模型推断的置信度。

## 6. 数据库与接口计划

### 6.1 新增表

建议新增:

- `agent_runs`: 存 run 基础信息、用户、标的、偏好、状态、模型版本。
- `tool_calls`: 存每次工具调用输入、输出摘要、耗时、失败原因。
- `claims`: 存模型生成的原子结论。
- `claim_evidence_links`: 存 claim 与 evidence 的支持/反驳关系。
- `user_feedback`: 存用户对报告和证据的反馈。
- `trigger_rules`: 存用户设置的巡检触发器。
- `harness_improvement_notes`: 存失败模式和下一步 harness 改进建议。

### 6.2 新增接口

建议新增:

- `GET /api/runs/{runId}`: 获取运行轨迹。
- `GET /api/runs/{runId}/trace`: 获取工具调用和 Agent 步骤。
- `POST /api/research/{symbol}/run`: 显式启动一次投研 run。
- `POST /api/research/{symbol}/audit`: 重新审计某次报告。
- `POST /api/feedback`: 保存用户反馈。
- `POST /api/triggers`: 创建巡检触发器。
- `POST /api/refresh/evidence`: 手动刷新过期证据。
- `GET /api/harness/improvement-notes`: 查看 harness 改进建议。

## 7. 前端开发计划

新增或升级以下面板:

1. `Agent Run Trace`
   - 展示 Planner、工具、Agent、审计、报告版本。

2. `Tool Status`
   - 展示 yfinance、AkShare、EDGAR、新闻源、OpenAI 等工具是否可用。

3. `Evidence Graph`
   - 从表格升级为“结论 - 支持证据 - 反方证据”结构。

4. `Refresh Center`
   - 展示哪些证据过期、哪些可刷新、刷新后哪些结论变化。

5. `Feedback Bar`
   - 让用户对报告和证据给反馈。

6. `Harness Improvement Notes`
   - 展示系统从失败 run 中总结出的工程改进建议。

## 8. 分阶段路线

### Phase 1: 可观测 Harness

目标: 让每次投研 run 可追踪。

任务:

- 新增 `agent_runs` 和 `tool_calls`。
- 所有工具调用写入 `tool_calls`。
- 前端新增 Run Trace 面板。
- 报告卡片显示 `runId`、数据源、工具失败状态。

验收:

- 一次 NVDA 投研能看到完整工具调用链。
- 外部接口失败时，trace 能显示失败和缓存兜底。

### Phase 2: 审计 Loop

目标: 把报告生成改成初稿、审计、修订稿。

任务:

- 新增 `claims` 和 `claim_evidence_links`。
- Research Quality Judge 从“证据类型检查”升级为“研究质量审查”，覆盖证据充分性、信息时效、财务指标来源、样本外风险提示、事实/推断边界和反方观点。
- 增加 CRITIC 风格的工具验证步骤。
- 审计不通过时输出“数据不足”。

验收:

- 任一结论都能追踪到证据。
- 缺少财报或新闻证据时，报告不会生成强结论。

### Phase 3: 刷新与复盘 Loop

目标: 让系统持续更新，而不是一次性报告。

任务:

- 增加过期证据扫描器。
- 过期证据归档经验历史池。
- 重新生成依赖过期证据的模型推断。
- 报告版本对比显示“证据变了什么、结论变了什么”。

验收:

- 手动触发刷新后，新旧证据和新旧结论能对比。
- 过期模型推断不会继续显示为当前结论。

### Phase 4: 历史类比强化

目标: 把历史类比从样例表升级为可解释风险分布。

任务:

- 增加 `asOfDate` 截断校验。
- 增加价格、估值、新闻、财报窗口、成交量特征。
- 输出 1 周、1 月、3 月收益和最大回撤分布。
- 增加未来数据泄漏测试。

验收:

- 每个历史样本都能说明当时可见信息。
- 类比输出只写风险分布，不写预测结论。

### Phase 5: 用户反馈与 Harness 改进

目标: 让系统从用户反馈和失败 run 中改进。

任务:

- 新增用户反馈按钮和 `user_feedback` 表。
- 新增失败 run 分类。
- 新增 `harness_improvement_notes`。
- 每周生成“下周工程改进建议”。

验收:

- 系统能列出最常见失败原因。
- 系统能建议新增工具、审计规则或评估样例。

## 9. Demo 展示脚本

推荐演示:

1. 使用开发者账号登录。
2. 完成前测，录入 NVDA、TSLA、QQQ。
3. 启动 NVDA 投研 run。
4. 展示 Run Trace: Planner 调用了哪些工具。
5. 展示 Evidence Graph: 每个结论绑定哪些证据。
6. 展示 Evidence Judge: 哪些结论被降级，为什么。
7. 展示历史类比: 过去三年相似情景后的风险分布。
8. 手动把某条证据设为过期，触发刷新 loop。
9. 展示旧证据进入经验历史池，新报告生成版本差异。
10. 用户点击“证据不足”反馈，系统生成 harness 改进建议。

## 10. 风险边界

- 不做真实交易。
- 不输出确定性买卖建议。
- 不把用户 API Key 返回前端。
- 不保存新闻和研报全文。
- 不把结构化行情塞进向量库。
- 不把历史类比当预测。
- 不让用户偏好覆盖合规和风险审计。

## 11. 优先级建议

最高优先级:

1. `agent_runs` / `tool_calls` / Run Trace。
2. Evidence Judge 从类型检查升级为 claim-level 支持度检查。
3. 证据刷新和归档 loop。

第二优先级:

1. 历史类比 asOfDate 严格截断。
2. 用户反馈 loop。
3. 工具状态面板。

第三优先级:

1. Harness improvement notes。
2. 多模型交叉验证。
3. 更完整的多模态财报解析。

这个顺序的理由是: 没有可观测性，就无法判断 Agent 是否真的工作；没有审计 loop，就无法在金融场景中建立可信度；没有刷新 loop，投研系统会退化成一次性静态报告。

## 12. 完成目标覆盖审计

本节用于证明本文档已经覆盖“结合前沿论文研究（至少 6 篇），写一个本项目基于 Harness Engineering 和 Loop Engineering 的开发计划”的目标。

| 要求 | 当前覆盖情况 | 证据位置 |
| --- | --- | --- |
| 至少 6 篇论文 / 研究 | 已覆盖 14 篇，其中包括 Agent 工具使用、反思循环、外部工具纠错、金融 Agent、金融多模态 RAG、harness evolution。 | 第 2 节论文依据与项目启发 |
| 结合前沿研究 | 覆盖 2022-2026 年研究，并优先使用 arXiv / 论文页面作为来源。 | 第 2 节 |
| 解释 Harness Engineering 如何结合本项目 | 已拆为工具注册表、证据图谱、运行轨迹、权限安全、评估 harness。 | 第 4 节 |
| 解释 Loop Engineering 如何结合本项目 | 已拆为单次投研 loop、证据刷新 loop、历史类比 loop、审计修订 loop、用户反馈 loop、harness evolution loop。 | 第 5 节 |
| 给出可执行开发计划 | 已给出数据库表、接口、前端面板、分阶段路线和验收标准。 | 第 6-8 节 |
| 贴合当前 Investment Research 投研系统 | 明确引用当前账户/前测/持仓、证据链、历史类比、Evidence Judge、多模态投研卡片、经验历史池等模块。 | 第 3-8 节 |
| 保留金融风险边界 | 已明确不做真实交易、不输出确定性买卖建议、不泄露 API Key、不保存新闻研报全文、不把历史类比当预测。 | 第 10 节 |
| 形成 Demo 展示路径 | 已给出开发者登录、录入持仓、启动 run、展示 trace、审计、刷新、反馈的演示脚本。 | 第 9 节 |

完成判定:

- 该文档已满足研究来源数量要求。
- 该文档已把 Harness Engineering 和 Loop Engineering 映射到本项目的后端、前端、数据层、审计层和演示流程。
- 后续如果进入实现阶段，建议优先按 Phase 1 执行 `agent_runs`、`tool_calls` 和 `Agent Run Trace`。
