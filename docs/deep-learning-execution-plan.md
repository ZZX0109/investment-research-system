# 深度学习时序模型执行计划

更新时间: 2026-07-03

## 目标

本项目的深度学习模块不是为了让 Agent 直接预测涨跌，而是把高成本、长上下文、易幻觉的金融时序判断前移到结构化模型层。模型输出低 token 的风险分布、局部信号、历史相似情景和校准状态，LLM 只负责解释、审计和组织证据链。

落地原则:

- 原始行情、财务指标和标签进入结构化库。
- 新闻、公告、财报文本进入文档检索库。
- 相似历史情景进入经验历史池。
- LLM 不读取三年逐日明细，只读取模型压缩后的特征摘要、风险分布和证据时间戳。
- 所有训练、推理和历史类比必须带 `asOfDate`，禁止未来函数。

## 已实现代码结构

```text
ml/
  common.py                         路径、SQLite、artifact 读写工具
  config/
    dataset.yaml                    数据集构建约定
    model.yaml                      模型族配置
    train.yaml                      训练配置
  data/
    build_dataset.py                从 historical_prices 构建点时样本
    feature_store.py                字段级 PIT 元数据与未来函数检测
    ingest_history.py               真实/ synthetic 历史行情 ingest
    point_in_time.py                未来数据泄漏检查
    providers.py                    synthetic smoke 数据源
    quality.py                      真实数据质量、复权、缺失、revision 与幸存者偏差报告
    splits.py                       时间切分和 embargo
  features/
    market.py                       收益、波动、回撤、成交量和窗口特征
    labels.py                       未来收益、最大回撤、风险状态标签
  models/
    tabular_baseline.py             可解释表格基线
    cnn_tcn.py                      CNN/TCN 局部形态编码器
    patch_tst_lite.py               PatchTST 轻量原型
    itransformer_lite.py            iTransformer 轻量原型
    scenario_encoder.py             相似情景 embedding
  training/
    registry.py                     model_registry 和 ML 表结构
    train.py                        训练入口
    evaluate.py                     评估入口
    calibrate.py                    校准入口
  risk/
    distribution.py                 风险分布、VaR breach 和 high-risk regime
  inference/
    predict.py                      最新特征构建、推理、risk_predictions 写入
    retrieve_scenarios.py           历史窗口 seeding、相似情景检索
    export_to_sqlite.py             批量推理导出
  reporting/
    token_compression.py            Agent token 压缩报告
  pipelines/
    minimal_demo.py                 最小 demo 训练/推理/验收
    real_data.py                    20-50 个真实标的的 risk_tabular_real_v1 训练/验收
    reliable_scale.py               一定规模可靠算法训练/验收
  tests/
    test_point_in_time.py
    test_splits.py
    test_labels.py
    test_risk_distribution.py
    test_validation_metrics.py
    test_token_compression.py
    test_inference_contract.py
    test_pipelines.py
```

## 模型路线

第一层: `tabular_baseline`

用途是建立可验证、可解释、可快速运行的风险基线。输入为收益、波动率、回撤、成交量异常和价格加速等结构化特征，输出 1 月风险状态、P50/P90 最大回撤、波动率和置信度。

第二层: `cnn_tcn`

用途是识别局部时序形态，例如价格加速、成交量异常、波动突变和短期回撤结构。它适合把高频局部模式压缩为 `localSignals`，减少 Agent 逐条读取长行情序列的 token 成本。

第三层: `patch_tst_lite` / `itransformer_lite`

用途是建模长窗口行情、财报窗口、新闻事件和行业状态之间的相互作用。第一版提供轻量实现与训练入口，后续可接入更大样本、更多资产和事件特征。

第四层: `scenario_encoder`

用途是把点时窗口编码为情景向量。用户添加股票后，系统从结构化历史行情中抽取候选窗口，匹配相似阶段，并展示后续 1 周、1 月、3 月收益和最大回撤分布。

## 数据和标签

当前数据集样本包含:

- `symbol`
- `market`
- `asOfDate`
- `featureVersion`
- `sourceStatus`
- `split`
- `window60`
- `window120`
- `tabular`
- `labels`

标签包含:

- `return_1w`
- `return_1m`
- `return_3m`
- `max_drawdown_1m`
- `max_drawdown_3m`
- `volatility_1m`
- `risk_regime_1m`

时间切分:

- 训练集: 2023 年以前
- 验证集: 2023 年
- 测试集: 2024-2025 年
- shadow: 2026 年以后，只用于推理和演示，不作为训练评估

## 数据库表

后端 SQLite 新增:

- `model_registry`: 模型版本、训练截止日、验证窗口、测试窗口、指标、状态和 artifact 路径。
- `feature_snapshots`: 每个标的每个 `asOfDate` 的点时特征快照。
- `risk_predictions`: 模型推理结果、有效期、校准状态和风险分布。
- `scenario_embeddings`: 历史情景 embedding。
- `similar_scenarios`: query 情景和匹配历史窗口的后续收益与回撤。

这些表只存结构化数据，不把三年逐日行情塞进向量库。

## 后端接口

- `GET /api/ml/models`
- `POST /api/ml/datasets/build`
- `POST /api/ml/train`
- `POST /api/ml/infer/{symbol}`
- `GET /api/ml/predictions/{symbol}`
- `GET /api/ml/scenarios/{symbol}`

`/api/research/{symbol}` 已集成 `mlRiskSummary`。Research Quality Judge 会检查模型是否有 `modelId`、有效期、校准状态和样本外记录；缺失或 stale 时会降级模型结论。

## 前端展示

投研卡片新增“时序模型风险分布”面板，展示:

- 模型状态
- `modelId`
- `modelType`
- `asOfDate`
- 校准状态
- 1 月 P50/P90 回撤
- 1 月波动率
- 相似历史情景表

Agent workflow 新增:

- `Time-Series Feature Builder Skill`
- `CNN Local Signal Skill`
- `Transformer Scenario Encoder Skill`
- `Calibration Validator Skill`

## 训练命令

Smoke 数据集:

```bash
python3 -m ml.data.build_dataset --symbols NVDA,TSLA,QQQ,XLE --output artifacts/datasets/investment_research_v1_smoke --allow-synthetic --smoke
```

训练表格基线:

```bash
python3 -m ml.training.train --model tabular_baseline --dataset artifacts/datasets/investment_research_v1_smoke --model-id tabular_baseline_v1
```

推理:

```bash
python3 -m ml.inference.predict --symbol NVDA --model-id tabular_baseline_v1 --allow-synthetic --write-sqlite
python3 -m ml.inference.retrieve_scenarios --symbol NVDA --write-sqlite
```

完整验证:

```bash
npm run verify
```

一键训练 pipeline:

```bash
npm run train:minimal
npm run train:real:smoke
npm run train:real
npm run train:real:deep:smoke
npm run train:scale:smoke
npm run train:scale
npm run train:scale:large
npm run train:scale:large:deep:smoke
```

真实数据最小算法:

```bash
python3 -m ml.pipelines.real_data --model-id risk_tabular_real_v1 --min-symbols 20 --min-samples 800 --max-samples-per-symbol 80 --compact-feature-metadata --window-mode none
```

300-600 标的扩展入口:

```bash
python3 -m ml.pipelines.reliable_scale --fetch-real --universe large_us_cn --min-symbols 300 --min-samples 12000 --min-rows 1250 --max-samples-per-symbol 40 --compact-feature-metadata --window-mode none --ingest-workers 8 --refresh-events --event-workers 8
```

规模深度候选:

```bash
python3 -m ml.pipelines.reliable_scale --fetch-real --universe large_us_cn --min-symbols 300 --min-samples 12000 --min-rows 1250 --max-samples-per-symbol 40 --compact-feature-metadata --window-mode window120 --ingest-workers 8 --refresh-events --event-workers 8 --train-deep
```

当前规模深度结果:

- 312 个真实标的，12480 条 live 样本，`allowSynthetic=false`。
- `risk_tabular_scale_v1`: `model_judge_v2=pass`，`model_registry.status=approved`。
- 规模数据质量: adjusted prices 312/312，dividends/splits 311/312，halts/missing 312/312，filing availableAt 287/312，announcement publishedAt 287/312，news publishedAt 226/312，revision history 312/312，survivorship disclosure 312/312。
- 披露补齐记录: 对缺失披露的 163 个 CN/A股/基金标的刷新公告/财报证据，成功 163/163，新增 disclosure 163、financial_report 163，错误 0。
- `cnn_tcn_scale_candidate_v1`: `research_candidate`，ECE 0.2835，pinball loss 0.0112，CRPS 0.0574，VaR breach rate 0.0659。主要问题是校准误差过高，暂不进入正式投研卡片。
- `patch_tst_lite_scale_candidate_v1`: `promotable_candidate`，ECE 0.1028，pinball loss 0.0112，CRPS 0.0644，VaR breach rate 0.0649。它是当前唯一可进入下一轮人工 model card 复核和 ablation 的深度候选。
- `itransformer_lite_scale_candidate_v1`: `failed_candidate`，ECE 0.0759，pinball loss 0.0226，CRPS 0.2610，VaR breach rate 0.0088。主要问题是分布质量和 VaR breach 不合格。
- 当前 `deepCandidateAudit=fail`。规模 pipeline 本身通过，是因为正式系统仍以 approved 的 `risk_tabular_scale_v1` 作为风险基线；深度模型只作为研究候选，不替代正式基线。
- 当前不可声称已经生产完备: 仍有 25/312 个标的缺财报/公告时间戳，86/312 个标的缺新闻发布时间，1/312 个标的缺分红拆股记录；这些缺口会影响事件特征、公告窗口和模型解释层可信度。

## 可靠性约束

- 不使用 `asOfDate` 之后的数据构造输入特征。
- 每个特征字段必须有 `asOfDate`、`source`、`availableAt`、`revisionId`，并通过未来函数检测。
- 相似情景匹配只用当时已知窗口；后续收益和回撤只作为历史结果展示。
- 真实数据不可用时允许 smoke synthetic，但 `sourceStatus` 必须为 `degraded`，模型状态降为 `stale`。
- `allowSynthetic=false` 时，历史行情加载会过滤 synthetic/demo/fallback 来源；真实训练会在确认真实历史足够后清理本批标的旧 demo 缓存，不得把 demo 缓存混入样本或质量报告。
- 真实训练必须输出数据质量报告，至少覆盖复权价格、分红拆股、停牌/缺失值、证据时间戳、revision history 和幸存者偏差说明。
- 深度候选必须输出 `deepCandidateAudit`。没有样本外指标、walk-forward 或 purged CV 的 CNN/Transformer 不能进入正式投研卡片。
- 模型推断不输出买入、卖出、目标价和仓位建议。
- 新模型必须进入 `model_registry`，未注册模型不能进入正式投研卡片。
- 模型超过有效期或依赖证据过期时，Judge 必须要求刷新或降级。

## 训练后优先开发项执行状态

第一优先级: Point-in-Time Feature Store。

已新增字段级 Feature Store。`point_in_time_features` 逐字段记录 `asOfDate`、`source`、`availableAt`、`revisionId`；`ml/data/feature_store.py` 负责生成元数据、校验缺失字段和检测 `availableAt > asOfDate` 的未来函数。数据集构建、最新推理和历史情景 seeding 都会写入 PIT 元数据。

第二优先级: Risk Distribution Engine。

已新增 `ml/risk/distribution.py`。输出未来 1 周 / 1 月最大回撤 P50/P90/P95、波动率 P50/P90、高风险 regime、VaR breach probability 和分布方法说明。系统不输出涨跌方向预测，只输出风险分布。

第三优先级: Calibration & Backtest Validator。

已升级 `ml/training/evaluate.py` 与 `ml/training/calibrate.py`。训练后写入 `calibration_ece`、`pinball_loss`、`crps`、`var_breach_rate`、`walk_forward` 和 `purged_cv`，并进入 `model_registry.metrics_json`。

第四优先级: Agent Token Compression Report。

已新增 `ml/reporting/token_compression.py` 和 `/api/ml/token-compression/{symbol}`。报告估算 raw 行情/证据/文档输入 token、结构化摘要 token、压缩率和结论一致性；前端投研卡片和 Markdown 报告均展示该结果。

第五优先级: Research Quality Judge v2。

已将审计器升级为 `judgeVersion=v2`。Judge 不判断股票涨跌，只检查未来函数、样本外验证、校准、来源引用、概率语言边界和反方观点；同时保留证据充分性、claim-level 支持和个性化荐股越界检查。

模型训练侧新增 `model_judge_v2`。`tabular_baseline` 只有在 ECE、pinball loss、CRPS、VaR breach、walk-forward、purged CV、样本外评估和 no-degraded-samples 全部通过后，才会在 `model_registry` 中进入 `approved`。CNN/TCN、PatchTST 和 iTransformer 仍保持 candidate，必须经过人工 model card 复核后才能进入正式投研卡片。

## 下一步训练升级

1. 扩充真实数据源: yfinance、SEC/EDGAR、AkShare、基金净值、财报日历、新闻事件时间线。
2. 加入事件特征: 财报前窗口、公告类型、新闻情绪、行业相对强弱、估值分位。
3. 做 purged walk-forward validation，防止相邻窗口泄漏。
4. 对回撤分位做 conformal calibration，输出可解释置信区间。
5. 增加 ablation: 无新闻、无估值、无成交量、无财报窗口，验证每类特征是否真实贡献精度。
6. 建立模型卡: 数据范围、适用资产、失败模式、校准曲线、样本外表现和合规边界。
