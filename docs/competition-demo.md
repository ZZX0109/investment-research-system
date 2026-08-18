# 长期投资 AI 研究助手 · 比赛演示手册

> 本文档面向比赛评委与演示操作者。系统基于现有 A 股量化研究平台改造，**大语言模型作为主研究助手**，编排知识库、联网搜索、行情财务计算、长期模型与组合风险工具，把多来源结果转化为**通俗、可追溯、不输出交易指令**的长期投资研究观察。

## 一分钟看懂系统价值

普通用户在一分钟内看到的是：

1. **输入问题** —— 一个提问框 + 三个示例问题，覆盖经营变化、长期风险、观察周期冲突。
2. **通俗回答（五段）** —— 经营情况 / 长期变化 / 可能的风险 / 还缺什么证据 / 依据和更新时间。
3. **证据可追溯** —— 每条结论都带来源、标题、发布日期与链接；区分已确认事实、基于事实的解释、来源冲突与仍缺失证据。
4. **安全边界** —— 全程“研究观察”，不输出买入、卖出、加仓、减仓、目标价或收益承诺；索要买卖建议时安全降级。

专业详情（四个长期任务、模型结构、训练范围、特征覆盖、评估指标、资料引用、运行状态）下沉到首页底部的折叠区与“专业研究台”视图，不作为首页主角。

## 系统边界（贯穿全场）

- 数据 `data_tier=research_pit / research_demo`，`deployment_ready=false`，`status=research_only`。
- 比赛演示数据 `validation_status=research_demonstration_not_validated`，明确标注为**研究展示数据**，非验证预测结果。
- 未启动正式训练，未修改下载中数据，未覆盖 active 数据（`artifacts/long_term_training/latest.json` 保持其原有 blocked 状态）。
- ETF 仅作市场参考与基准，不参与股票排名。

## Agent 工具调用流程

用户提问后，Agent 按以下顺序编排（详见 `src/investment_research/agent/service.py`）：

1. **问题识别** `task_intake` / `task_classification` —— 判断是否长期问题。
2. **知识库检索** `search_financial_knowledge` —— PIT 过滤的历史财报、公告、公司资料、行业背景，带 `citation_id`。检索前先经 **查询规划** `knowledge_query_planner` 把"经营变化"等简短问题展成营业收入/净利润/毛利率等子查询并链接公司代码；一阶段混合（词法+语义、权威加权）取 top-N 后经 **cross-encoder 重排**（默认确定性 `deterministic-fallback`，设 `INVESTMENT_RESEARCH_ENABLE_NEURAL_RERANKER=1` 启用本地 `bge-reranker`，不可用自动降级）。
3. **结构化财务科目** `get_financial_line_items` —— PIT 可见的营收/净利/毛利率/研发占比等结构化数据，带期间、同比、来源；缺期记为"未披露"而非零。
4. **最新信息搜索** `search_latest_news` —— 联网搜索最新公告、新闻、监管变化、行业事件，保留来源/标题/发布日期/链接；离线时降级到研究演示索引并标注。
5. **财务与行情计算** `get_price_trend` —— 收盘价、20 日收益与波动。
6. **长期模型读取** `get_long_term_scorecard` / `get_long_term_model_readings` / `get_long_term_data_trust` / `get_long_term_evidence_balance` / `get_long_term_fact_cards` —— 只读四个长期任务读数与五维评分。
7. **组合风险分析**（询问组合时）`portfolio_risk` —— 组合集中在哪里、可能受什么影响、还需补什么信息。
8. **证据合并** `evidence_merge` —— 合并知识库 + 联网搜索 + 模型读数 + 计算，分为已确认事实 / 基于事实的解释 / 来源冲突 / 仍缺失证据。来源冲突经 **冲突仲裁**（权威 > 时效 > 印证；未决保留双方，不静默取舍），输出 `resolved_stance` 与 `reasoning`。
9. **因果推理** `reasoning_chain` —— 把五维评分 + 双周期读数 + 事实卡 stance + 财务科目 + 仲裁结果连成 2-3 条因果观察，每条引用 ≥2 条证据线索 + ≥1 条证伪条件。
10. **合规检查** `compliance` —— 拦截买卖、加仓、减仓、目标价、收益保证。
11. **通俗回答** `plain_answer` —— 输出五段结构 + 因果观察，隐藏 q10/q50/q90 分位数与模型名称。

Agent 不得自行修改模型数值、不得凭空补造区间、不得把未知数据当作零风险、不得把搜索摘要当作事实而不保留来源、不得把单一新闻直接解释成长期结论。

## 长期模型与五维评分（后台证据）

四个长期任务（`artifacts/competition_demo/long_term_research_demo.json`，研究展示数据）：

| 任务 | 含义 | 普通用户看到的说法 |
| --- | --- | --- |
| `excess_return_120d` | 未来约 6 个月相对基准超额表现 | “相对基准的长期表现观察” |
| `excess_return_240d` | 未来约 12 个月相对基准超额表现 | “相对基准的长期表现观察” |
| `future_max_drawdown_120d` | 未来约 6 个月潜在最大回撤 | “潜在下跌幅度观察” |
| `future_max_drawdown_240d` | 未来约 12 个月潜在最大回撤 | “潜在下跌幅度观察” |

五维评分：经营质量、成长稳定性、估值位置、股东回报、长期风险（+证据完整度）。后台保留多个候选模型供专业详情比较；普通用户只看到综合后的通俗长期观察。

## 三个可重复演示案例

### 案例 1：经营变化（600519 示例白酒）

- **问题**：请解释这家公司最近经营发生了什么变化
- **工具调用摘要**：`collect_pit_evidence` → `get_long_term_scorecard` → `get_long_term_model_readings` → `get_long_term_data_trust` → `get_long_term_evidence_balance` → `get_long_term_fact_cards` → `search_latest_news` → `quality_gate`
- **主要证据**：
  - 知识库：公司资料、分红政策（来源 `知识库`，2026-06-30）。
  - 联网搜索：示例白酒发布 2026 年中期报告（来源 `交易所公告`，2026-08-12，链接 `https://example-exchange.com/600519-mid-2026`）；消费板块景气度跟踪（来源 `研究资讯`，2026-08-10）。
  - 长期模型读数：约 6 个月相对基准偏强、约 12 个月相对基准中性；潜在下跌幅度中等。
- **通俗回答要点**：经营质量偏稳、成长稳定中等；长期表现观察约 6 个月偏强、约 12 个月中性；估值位置偏高需持续关注。
- **引用来源**：见回答底部“依据和更新时间”与“引用来源”折叠区。

### 案例 2：长期风险（300750 示例电池）

- **问题**：如果我长期关注这家公司，主要风险是什么
- **工具调用摘要**：同上流程。
- **主要证据**：
  - 知识库：盈利波动较大、行业景气度存在分歧。
  - 联网搜索：新能源行业产能与价格跟踪（来源 `行业研究`，2026-08-09）；定增与产能规划公告（来源 `交易所公告`，2026-08-05）。
  - 长期模型读数：约 12 个月潜在下跌幅度偏大；长期风险读数偏高。
- **通俗回答要点**：长期风险读数偏高、估值位置中等；约 12 个月潜在下跌幅度偏大；行业景气度与盈利变化存在分歧；提醒关注波动与负面信息，**不构成卖出或调仓建议**。

### 案例 3：模型读数冲突（000858 示例食饮 / 300750 示例电池）

- **问题**：基本面看起来不错，但不同观察周期结果不一致，为什么
- **工具调用摘要**：同上流程。
- **主要证据**：约 6 个月相对基准偏强，但约 12 个月相对基准偏弱（同一公司两个周期读数方向相反）。
- **通俗回答要点**：用通俗语言解释差异——“经营质量目前尚可，但未来表现观察偏弱，主要因为行业景气度和盈利变化存在分歧”；说明需要继续关注的指标（下一次定期报告、行业相对表现、融资变化）以及可能推翻当前判断的条件（新的公告、财报修订、行业归属变化）。

## 失败案例展示

| 失败场景 | 系统行为 | 用户看到 |
| --- | --- | --- |
| 资料不足 | 长期评分卡/读数缺失 → `_long_term_abstain_reasons` → abstain | `result_status=insufficient_evidence`，明确“还缺什么证据”，不强行下结论 |
| 来源冲突 | 知识库历史资料与最新公开信息方向相反 → `evidence_merge` 标记 conflict | `result_status=conflict_present`，提示交叉核对来源与发布日期 |
| 模型读数冲突 | 120d 与 240d 方向相反 | 通俗解释差异并说明需继续关注的指标 |
| 数据日期过旧 | `get_long_term_data_trust` 未通过核验 → abstain | “数据日期过旧，建议补齐后刷新” |
| 索要买卖建议 | “能不能买入？” → `compliance` 拦截 → 降级为研究观察 | 五段回答中不含买卖/加仓/减仓/目标价/收益承诺，`compliance_allowed=true` |

> 对应自动化测试：`tests/test_competition_demo_flow.py`、`tests/test_research_text_compliance.py`、`tests/test_plain_answer.py`、`tests/test_evidence_merge.py`、`tests/test_web_search.py`、`tests/test_portfolio_risk.py`。

## 比赛评价维度

| 维度 | 如何在本系统体现 |
| --- | --- |
| 引用正确资料 | 每条结论带来源/标题/发布日期/链接；`citation_audit.source_count` |
| 能否获取最新信息 | `search_latest_news` 联网搜索（可配置 HTTP provider，离线降级到研究演示索引） |
| 避免无依据结论 | `evidence_merge` 区分事实/解释/冲突/缺口；缺证据时 `result_status=insufficient_evidence` |
| 用户是否看得懂 | 五段通俗回答，隐藏分位数与模型名称 |
| 用户是否知道下一步观察 | `next_observation_conditions` + `invalidation_conditions` |
| 工具调用是否正确 | `tools_used` 暴露只读工具序列；`agent-runs/{id}/tool-calls` 可审计 |
| 是否稳定拒绝交易指令 | `compliance_audit` + `_contains_trade_instruction`；买卖请求安全降级 |

## 启动演示

```bash
# 1. 生成比赛演示数据（如未生成）
python3 scripts/build_competition_demo_fixtures.py

# 2. 播种知识库（3 家演示公司的文档、事实卡、结构化财务科目）
python3 scripts/seed_competition_knowledge.py

# 3. 启动研究平台（后端 + 前端）
npm run dev:research-platform
#   首页即为“长期投资 AI 研究助手”，可切换“专业研究台”查看技术详情。

# 4. 运行全部测试
python3 -m pytest -q --ignore=tests/training   # 后端
npx vitest run                                  # 前端

# 5. 评估知识库检索质量（recall@k 与 citation-validity）
python3 scripts/evaluate_competition_kb.py
#   典型结果：recall@3≈1.0、citation_validity=1.0（详见 artifacts/competition_demo/latest-kb-evaluation.json）
```

知识库支持层（支持 LLM 做深度分析的底座）：

| 能力 | 说明 |
|---|---|
| PIT 事实卡 + 结构化科目 | 事实卡带 stance/authority/confidence；财务科目带期间/同比/来源，缺期=未披露 |
| 版本化与 supersede | 文档与科目按 content_hash 去重、修订化、更正版替代旧版 |
| 覆盖率语义 | `absence_is_evidence` 只在覆盖率可证时成立，否则记 `unknown`，不臆造"无风险" |
| 查询规划 + 实体链接 | 简短问题展成话题子查询，公司名/代码归一到 ticker |
| 混合检索 + 重排 | 词法+语义权威加权一阶段 → cross-encoder 二阶段重排（可降级） |
| 冲突仲裁 | 权威 > 时效 > 印证，未决保留双方，输出 resolved_stance + reasoning |
| 因果推理 | 五维+双周期+事实卡+科目+仲裁 → 2-3 条因果观察 + 证伪条件 |
| golden eval | 15 题 recall@k + citation-validity，CI 守护 |

可选联网搜索 provider（默认离线演示索引）：

```bash
export INVESTMENT_RESEARCH_WEB_SEARCH_ENDPOINT=https://your-search-provider.example/search
export INVESTMENT_RESEARCH_WEB_SEARCH_API_KEY=...
# 可选：启用本地 bge-reranker 神经重排（默认确定性重排，更快且无网络依赖）
export INVESTMENT_RESEARCH_ENABLE_NEURAL_RERANKER=1
```

## 中性表达约定

普通用户界面统一使用“研究观察”“资料日期”“结果状态”“尚待补充的信息”“下一步观察条件”等中性表达。所有未经完整验证的结果继续作为研究展示，不包装成上涨概率、买卖信号或收益承诺。

## 选股 → 仪表盘 → AI 同源链路（Phase 2-8）

整条链路围绕一个**单一事实源** `AssetSnapshot`：仪表盘 tiles 和 AI 回答读同一份快照，用户不会在两侧看到不同的数。

```
选股器(assets) ─┐
               ├─► GET /api/v1/assets/{id}/snapshot?as_of=  (AssetSnapshotService · 只读聚合 · 无 run/无 abstain)
               │        │
               │        ├─ market_observation(收盘/20日回报/波动)
               │        ├─ directional_forecast(tile_text · 合规框架表述 · 非买卖建议)
               │        ├─ scorecard + model_readings(四长期任务 · 后端证据)
               │        ├─ fact_cards / line_items(content_hash 单源去重)
               │        ├─ evidence_merge_result(EvidenceMerger 单一证据层)
               │        └─ causal_observations(ReasoningChainBuilder)
               │
仪表盘 tiles ◄─┤  (useAssetSnapshotQuery 渲染 latest_close / return_20d / tile_text / 事实卡数 / data_as_of)
               │
AI 多轮 ◄──────┘  POST /api/v1/conversations  →  POST /conversations/{id}/messages
                        │  ConversationAgentService: 建 snapshot(pin session.as_of) → run(snapshot=) → 存 assistant 答复
                        │  _build_plain_answer(snapshot=) 直接吃快照值 → 消除漂移
                        └─ GET /api/v1/agent/runs/{id}/events (SSE · 工具进度: 检索中/读模型中/合并证据/合规检查)
```

**前端入口**：首页顶部新增 `选股·仪表盘·AI` 视图标签（`StockWorkspacePage`），三栏布局——左选股器、中仪表盘 tiles、右 AI 多轮面板（含五段通俗回答 + 工具进度态）。原 `长期投资助手` 与 `专业研究台` 视图不变。

**承重级重构（支撑同源链路的地基）**：

| # | 重构 | 落地 |
|---|---|---|
| 5 | 抽 `agent/models.py` 断环（共享模型） | Phase 0 ✓ |
| 1 | `EvidenceMerger` 接为单一证据层（删并行分类） | Phase 1 ✓ |
| 2 | `AssetSnapshotService` + snapshot 路由 + `_build_plain_answer(snapshot=)` | Phase 2 ✓ |
| — | `ConversationSession` 域 + 迁移 0021 + 路由 + `prior_turns` | Phase 3 ✓ |
| 4 | 拆 god-class：`DashboardReadService`(只读) + `ConversationAgentService`(多轮) + `KnowledgeQueryPlanner.retrieve()`(查询规划外提) | Phase 4 A1+A2+A3 ✓ |
| — | 预测 tile 合规框架 `frame_prediction_as_observation()`（snapshot 与 AI 共用） | Phase 5 ✓ |
| — | 工具进度 SSE `GET /agent/runs/{id}/events` | Phase 6 ✓ |
| 2/3 | reranker 接 `as_of` + `FinancialLineItem.content_hash_of` 单源 | Phase 7 ✓ |
| 6 | TS 类型同步 `AssetSnapshot/ConversationSession/ConversationMessage/AgentEvent` + `StockWorkspacePage` + e2e | Phase 8 ✓ |

> Phase 4 的"会话路径跳过 asset-scoped 工具执行"已通过 `tool_overrides` 扩展点落地于 KB 命重工具（`get_financial_line_items` + `get_long_term_fact_cards`：快照已带其同形状值，覆盖结果与工具原返回一致，abstain 门禁不受影响）；四个长期 abstain-gate 工具（scorecard/readings/data_trust/evidence_balance）仍运行——它们是已加载评分卡的廉价派生，覆盖需重建 `long_term_response`（快照未带 data_trust/evidence_balance），高风险低收益，留作后续快照 schema 扩展。当前 AI 回答已通过 `_build_plain_answer(snapshot=)` 使用快照值，无漂移。

### 启动与验收

```bash
# 后端
python3 -m pytest -q --ignore=tests/training        # 全绿（308+）
# 前端
npx vitest run                                       # 全绿（含 workbench-e2e 选股·仪表盘·AI）
npx vite build --config workbench-ui/vite.config.ts  # 成功
# 演示
python3 scripts/start_research_platform.py           # 起后端
# 浏览器打开 workbench，切到「选股·仪表盘·AI」视图标签
```
