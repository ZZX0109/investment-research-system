# A 股量化研究平台技术白皮书

## 摘要

本平台是一个零预算、研究级、可复现、证据驱动的 A 股量化研究系统。它以“研究结论必须能追溯到数据、快照、特征、模型和后续结果”为核心原则，而不是把模型输出包装成即时交易建议。当前公开数据主线只覆盖 A 股日线及少量 ETF，运行上下文固定为 `CN + close_confirmed`；四市场、分钟数据、盘中推理和正式授权发布保留为架构扩展，不是当前交付目标。

系统产出四个彼此独立的研究任务：未来 1 日方向三分类概率、未来 5 日方向三分类概率、未来 20 日收益 P10/P50/P90 区间，以及未来 20 日最大回撤分布与阈值回撤概率。它同时输出数据质量、覆盖率、模型版本、证据状态、模型分歧、拒答原因和 Shadow 前向验证状态。系统不输出买卖指令，不承诺收益，也不把风险概率解释为上涨或下跌概率。

## 1. 产品定位与可信边界

### 1.1 研究模式与正式模式

平台把“数据资格”与“模型研究能力”分开处理。

| 数据等级 | 来源要求 | 允许用途 | 禁止用途 |
| --- | --- | --- | --- |
| `test_fixture` | 构造测试数据 | 单测、集成测试、演示验证 | 研究结论、训练报告、用户界面结论 |
| `research_pit` | 公开回补数据，可记录抓取时间但通常无法证明历史可见时间 | 研究训练、walk-forward、模型消融、研究推理、Research Shadow | 正式 PIT、正式审批、正式部署 |
| `formal_pit` | 授权/SLA、历史 `available_at`、revision、证券状态、公司行动与完整链路 | 正式训练、审批、正式推理、正式 Shadow | 无 |

免费 AKShare、Baostock 与公开披露数据属于 `research_pit`。它们通常能支持收盘后实验和每天的前向记录，但不能证明每一条历史记录在某个过去决策时点已经真实可见。因此所有免费数据产物必须带有 `historical_available_at_unproven_public_backfill` 限制，且固定为：

```text
status=research_only
deployment_ready=false
```

这不是工程降级，而是明确不同数据资格对应的不同产品承诺。

### 1.2 当前系统回答的问题

平台可回答：

- 在某个冻结的收盘研究快照下，模型对 1 日/5 日方向的概率分布是什么？
- 20 日收益的保守、中性、乐观分位数分别是什么？
- 未来 20 日发生显著最大回撤的研究风险如何？
- 哪些输入事实、数据质量问题、Provider 状态和模型分歧影响了这一结果？
- 当前结论是否应被拒答？过去冻结的结论在后续 1/5/20/60 个交易日表现如何？

平台不回答：

- “现在应不应该买入/卖出？”
- “明天一定涨还是跌？”
- “这个模型已经可以实时交易吗？”
- “公开数据回补能否证明历史上没有未来信息？”

## 2. 总体架构

```text
免费 Provider（AKShare / Baostock）
        │
        ▼
Raw append-only payload + fetch observation + hash
        │
        ▼
Standard revision（统一代码、OHLCV、复权、状态、质量）
        │
        ▼
冻结 MarketSnapshot（研究池、日历、revision、覆盖、质量）
        │
        ├──────────────► Feature V2 / Sequence windows
        │                         │
        │                         ▼
        │                    Sample + labels
        │                         │
        │                         ▼
        │               Walk-forward / OOF calibration
        │                         │
        ▼                         ▼
Research roster ◄── manifest、报告、artifact hash
        │
        ▼
精确 scope 推理 → abstain / research_only 结果 → Research Shadow
        │                                                  │
        └──────────────────────────────────────────────────┘
                         1/5/20/60 日 append-only 回填
```

关系数据库保存目录、版本、hash、血缘、状态、快照和审批证据；对象存储/本地目录保存原始 payload、Parquet、模型、校准器和报告。SQLite 仅承担本地开发与一个兼容周期，生产权威存储应为 PostgreSQL 与对象存储。

## 3. 时间语义与 Decision Context

### 3.1 统一时间字段

所有数据类型至少区分以下时间：

| 字段 | 含义 | 能否直接当成模型可见时间 |
| --- | --- | --- |
| `event_time` | 事件实际发生时间 | 否 |
| `source_time` | Provider 标记的源时间/交易所时间 | 否，需结合延迟与采集记录 |
| `published_at` | 公告/新闻首次发布时间 | 可作为事件候选边界，但仍需确认采集/可见时间 |
| `ingest_time` / `received_at` | 系统接收数据时间 | 可用于证明本系统何时收到 |
| `available_at` | 明确可被模型使用的时间 | 是，正式 PIT 的关键字段 |
| `decision_time` | 本次研究做出决策的冻结时间 | 特征筛选上限 |
| `as_of` | 快照所声明的数据截至时间 | 仅描述快照，不取代字段级可见性 |

所有训练和推理输入都应满足：

```text
available_at <= decision_time
```

公开历史回补无法证明历史 `available_at` 时，系统不伪造该字段的正式含义，而是记录研究可见性假设。

### 3.2 当前决策上下文

当前主线只自动调度：

```text
市场：CN
上下文：close_confirmed
时区：Asia/Shanghai
默认冻结：交易日 15:10 后的确认延迟
```

`pre_open`、美股/港股/日股和分钟级上下文在类型与接口中保留，但不在零预算主线调度、训练或 UI 主入口中宣称可用。中国收盘后披露、周末披露及数据修订不得反向进入过去收盘样本。

## 4. Research PIT 数据体系

### 4.1 Raw 层

Raw 层 append-only 保存每次 Provider 返回的原始字节、请求参数、Provider、request ID、抓取时间、payload hash、schema version、覆盖窗口、市场阶段和抓取结果。相同内容 hash 的原始字节可以去重，但每次抓取 observation 都必须保留，以便回答“系统何时向哪个来源请求过什么”。

### 4.2 Standard 层

Standard 层统一证券代码、交易所、交易日历、时区、OHLCV、成交额、raw/qfq/hfq 口径、复权因子、停牌、ST、涨跌停、一字板、可交易状态、Provider、revision 和 active 指针。修订不会覆盖旧记录，而是创建新 revision；回放历史快照时只能读取当时冻结的 revision。

收益标签通常使用快照冻结的 qfq/总收益口径；涨跌停、停牌、成交量和成交额始终使用 raw 口径，避免复权把交易制度状态扭曲为普通数值。

### 4.3 Feature 与 Sample 层

Feature 层从同一个 `MarketSnapshot` 生成，离线训练和在线推理复用实现。每行保存 feature hash、输入 revision、覆盖率、质量状态、缺失掩码和 PIT 可见性说明。Sample 层把特征和未来标签连接，并至少保存：

```text
symbol / market / decision_context / decision_time / feature_cutoff
market_snapshot_id / market_snapshot_hash
feature_version / label_version
event_coverage_status / data_quality_status
historical_cohort_version / adjustment_policy
label_start / label_end / data_tier
```

### 4.4 事件覆盖状态

事件“没有”与事件“无法获取”是不同事实。系统固定使用：

```text
events_present
confirmed_none
unsupported
fetch_failed
pending_update
partial
```

只有前两种状态可产生有效零事件特征。其余状态必须进入 `event_missing_mask`、质量报告、模型输入和页面降级原因。把抓取失败填成零会让模型错误学习“数据缺失等于没有风险”，这是被严格禁止的。

## 5. 免费数据 Provider 与质量 Gate

### 5.1 公开数据链路

CN 当前价格 Provider chain 固定为：

```text
AKShare（主） → Baostock（备用/交叉校验）
```

AKShare 是公开金融数据接口，Baostock 是无需注册的研究数据来源。二者仅适用于研究和回补。CN 路径不允许把 yfinance 作为当前 PIT 回退；旧记录如存在，应标记为 `legacy_yfinance_excluded`，不得进入新训练或新 roster。

每个 `provider × symbol × adjustment_mode` 保存持久化 cursor。日常更新从上次成功交易日前回退若干交易日重叠抓取，用于发现 revision。AKShare 默认限速 2 请求/秒，Baostock 1 请求/秒，最多重试四次，采用递增退避与抖动。

### 5.2 质量规则

训练前和推理前都检查：

- 交易日连续性、重复 bar、交易日历与时区。
- OHLC 合法性、非正价格、成交量和成交额异常。
- raw/qfq 复权一致性与 revision。
- 停牌、ST、涨跌停、一字板、上市不足、退市或代码状态未知。
- Provider 切换、主备冲突、缓存新鲜度、覆盖率与事件状态。
- cohort 版本、snapshot ID/hash 一致性、`data_tier=research_pit`、`synthetic_count=0`。

首次回补对 ETF 进行全量 AKShare/Baostock 对账；股票采用确定性轮换对账。收盘价偏差超过 0.2%、成交量偏差超过 2%，或交易日集合不一致时，标的被标记为 `provider_conflict`，当日正常推理必须拒答。

### 5.3 缓存和降级

缓存不是“文件存在即有效”。每项缓存都记录来源、抓取时间、最新源时间、覆盖范围、质量和过期时间，状态为 `fresh`、`stale_usable`、`expired` 或 `unavailable`。超过三交易日的缓存只能使任务 `abstain`。Provider 降级和缓存回退必须在数据状态与页面中可见。

## 6. 历史证券池、标签与可交易性

固定研究池优先选择沪深流动性较好、上市时间足够长、覆盖完整的股票，加上 5 只 ETF 基准。它减少免费数据下的噪声，但不消除幸存者偏差；若缺少可靠的历史证券状态/成分变化，报告必须说明“固定研究股票池限制”，不得冒充全市场表现。

标签从决策后的首个可交易开盘价开始。停牌或无法买入的一字涨停最多顺延 5 个交易日；仍不能入场则标签不可用。20/60/120 日最大回撤以入场价和窗口内日内低点计算，停牌保留状态但不伪造交易价格。窗口不足的样本直接排除。

方向标签与风险标签独立：方向任务保存原始收益、MAE、MFE、涨跌停状态、停牌和可交易性；边界可使用波动率标准化和版本化交易成本下限。任何方向结论都不得从回撤概率推导。

## 7. 特征、掩码与时序窗口

`investment-risk-features-v2` 保留价格、波动、成交量、市场、行业、事件和基本面等结构化特征，并扩展换手率分位、相对流动性、市场宽度、行业强弱、涨跌停状态、两融/资金替代指标和公告类别。每个特征应报告缺失率、非零率、市场覆盖和 PIT 可用时间；低覆盖特征不能以 0 假装有效。

深度模型使用真实窗口序列而非把一行表格复制成伪序列。`SequenceDatasetBuilder` 为每个标的按交易日构建 20、60、120 日窗口，输入包含：

```text
收益/对数收益、成交量变化、波动率、指数与行业状态、事件状态
data_quality_mask、event_missing_mask、feature_missing_mask
provider_id、revision_id、source_delay、cache_state
```

关键价格字段缺失、快照不一致、Provider 冲突或缓存过期的样本不能进入正常预测。标准化、imputer、特征选择和 normalizer 只在训练窗拟合，并以 hash 写入 manifest；验证、最终留出和线上推理只加载，不重新拟合。

## 8. 训练与时间外验证

所有候选在同一快照、同一特征合同、同一标签版本和同一时间 fold 上比较。当前默认协议：504 个交易日训练窗、126 个交易日验证窗、任务 horizon 等长 purge/embargo、最近 252 个交易日一次性最终留出，其中最近 126 个交易日为压力切片。

purged walk-forward 的关键规则是：若训练样本 `label_end` 穿过验证起点，则该样本从训练集删除；相邻滑动窗口不得让同一个未来标签区间同时出现在不同 fold。最后 12 个月不能参与调参、模型选择、阈值选择或校准。

校准只使用 time-OOF 预测。方向与风险任务可比较 Platt、isotonic、beta calibration；收益任务检查 P10/P50/P90 覆盖与 pinball loss。最终输出保留 raw score、校准概率、置信区间、覆盖率和拒答原因。

## 9. 模型族与晋升原则

传统模型是研究主线：逻辑/线性模型提供最低可解释基线，随机森林、LightGBM、XGBoost 负责主要非线性比较。方向还比较恒定类别、指数方向、动量与随机基线；收益比较历史分布与分位数基线；风险比较历史分布与概率基线。

深度模型是 challenger：Deep MLP 处理窗口池化/多尺度统计；TCN 使用因果膨胀卷积捕捉局部冲击；PatchTST 沿时间维做 patch；iTransformer 沿变量维学习跨变量关系。它们不因复杂而自动替代传统模型。

每个深度实验固定种子 `42`、`2026`、`3407`，记录配置、训练曲线、数据/feature/fold hash、每个种子的 artifact hash 和评估。分类模型只有在至少两个有效 regime 中相对最佳表格模型 AUROC 提升至少 0.03，且 Brier/ECE 不恶化、覆盖率下降不超过 2 个百分点、三种子稳定，才可进入 candidate/shadow；收益模型需在多个 regime 稳定改善 pinball loss。即使达到研究候选门槛，免费数据模型依然是 `research_only`。

## 10. 评估、regime 与成本

系统至少按 bull、bear、range、high_vol、行业、标的类型和数据质量状态拆分指标。

| 任务 | 核心指标 |
| --- | --- |
| 方向 | Macro-F1、balanced accuracy、macro AUROC、PR-AUC、log loss、ECE、覆盖率、拒答率 |
| 收益 | pinball loss、P50 MAE、方向命中率、P10-P90 覆盖率、Spearman IC |
| 回撤 | AUROC、PR-AUC、告警 precision、漏报率、Brier、ECE、drawdown lift |

策略相关研究评估加入 T+1、佣金、印花税、滑点、流动性、停牌和涨跌停约束。它们用于解释模型排序的研究价值与局限，不转化为可执行交易建议。

## 11. Roster、artifact 和运行时校验

模型文件本身不是发布事实。每个任务每个 scope 必须有独立 `task_manifest.json` 与 `research_model_roster.json`，包含：

```text
task / model_version / training_run_id / dataset_hash
market_snapshot_hash / feature_contract_version / label_version / fold_hash
selected_candidate / artifact_hashes / report_hashes
status=research_only / research_ready / deployment_ready=false
```

模型、feature order、scaler、imputer、calibrator、集成权重、regime router、数据快照、依赖与报告均保存 hash。推理时重新校验；任一不一致必须 `abstain`。推理只允许加载精确的 `CN + close_confirmed + cohort + task` roster，禁止读取任意训练目录、旧 bundle 或跨任务 fallback。

传统 primary、fallback 和 challengers 都被 roster 显式声明。候选没有稳定超过基线时，基线仍为 primary；不得为了页面展示强制升级复杂模型。

## 12. 集成、分歧与拒答

方向集成可以融合各模型 up/down/flat 概率；收益集成融合 P10/P50/P90；回撤集成融合风险概率、排序分数和一致性。权重只能由 time-OOF 和近期 regime 的时间外表现生成，且每个任务/状态保存独立版本。

当方向总变差、回撤概率差或收益 P50 差超过预设阈值时，系统输出 `abstain` 并记录分歧来源。其它拒答原因包括特征覆盖不足、缓存过期、Provider 冲突、关键价格缺失、artifact hash 不一致和输入分布超出训练范围。拒答不是空对象，而是带 reason code、数据状态和下一步条件的研究结果。

## 13. Research Shadow 与结果复盘

每个有效收盘 session 仅冻结一次预测。预测记录是不可变事实：snapshot、数据质量、模型/校准器 hash、所有候选输出、集成权重、分歧、影响事实、abstain 原因和结果均分别存储。回填在 1/5/20/60 个有效交易日后 append-only 写入收益、最大回撤、MAE/MFE、方向、停牌、涨跌停和数据完整性。

复盘分类包括数据错误、方向错误、风险等级错误、事件遗漏、证据解释错误、正确拒答和错误拒答。概率模型应以概率评分和校准结果判断，而不是把单次涨跌简单贴为“正确/错误”。20 个有效 session 才生成首份前向报告，60 个 session 后才能讨论替换 research primary。

## 14. 语言模型、证据与 Agent 边界

内部类型化状态机是唯一执行器，依次完成任务 intake、任务分类、受控计划、工具选择、证据收集、结构化特征构建、模型推理、反方证据检索、自审、repair/abstain 和固定报告。每个节点持久化输入 hash、schema、尝试次数、输出摘要、错误和审计事件。

语言模型仅处理任务分类、受控计划、反方检索意图、引用审计与自然语言解释；不计算收益、回撤或风险概率，不生成 SQL/URL/代码，不修改事实，不生成买卖指令。任何引用不存在的 Evidence ID 会使该次调用无效。无 LLM 时系统可生成确定性研究报告，但不会降低数据、模型或引用 Gate。

事实链为：

```text
Source → SourceDocument → SourceRevision → Evidence → Citation → Claim
```

相同 normalized hash 去重，新内容创建 revision，不覆盖旧事实。完成态 ResearchRun 固定输入快照、Evidence revision、FeatureContract、ModelRun、GateEvaluation 和 Report version，以支持报告回放与审计。

## 15. 安全、权限与运维

工具仅能来自 allowlist；凭据通过加密 vault 使用，不进入 prompt、日志或缓存。对象存储保存原始 PDF、页面和表格，关系库保存 hash、定位、权限与血缘。核心资源带 owner；未授权用户只能读取明确许可的固定 run。

Provider 失败按配置的 fallback 处理，不能重启或污染其他范围。模型 primary 失败只能切换同 scope 已批准/声明的 fallback；两者都失败输出 `risk_unavailable` 或 `abstain`。synthetic 数据不能冒充 real，缓存必须保留真实抓取时间。

## 16. 正式授权路径

正式路径需要 PostgreSQL、对象存储、授权主备数据源、SLA、历史 `available_at`、revision、证券状态、公司行动、PIT/leakage audit、独立审批、artifact hash、回滚产物和至少 20 个有效正式 Shadow session。正式模型的发布单位是：

```text
market × decision_context × task
```

免费研究数据不能通过修改 manifest、切换 UI 模式或复用旧 checkpoint 进入正式路径。若任何资格证据缺失，系统必须 fail closed 并返回 `blocked`。

## 17. 可复现性承诺

一次可复现研究 run 应能从最终页面或报告反向追溯到：原始 payload、Provider observation、standard revision、历史证券状态、MarketSnapshot、feature 行、sample、label、fold、训练 run、calibrator、评估报告、artifact hash、roster、推理输出与 Shadow 回填。缺少其中任一关键环节时，系统应明确显示限制或阻断，而不是用默认值补齐。

这套约束的价值不在于让模型看起来更复杂，而在于让研究结论可以被验证、被反驳、被回放，并在证据不足时诚实地拒绝判断。
