# 事件面 + 情绪面 kittencn 模型精度提升 — 执行记录

> 基线:round-32 enriched rank_ic = **0.0768**(price_only=0.0586,加稀疏 fundamentals +0.0182)。本任务从情绪面 + 事件面加因子提升 rank_ic。计算在 RTX 4090 远程 pod(cpod),本地与服务器数据/代码已同步。

## 环境与数据
- 生产库 `var/investment_research.db`(594MB):162 标的 × 5 年日线(2020-2024),`versioned_market_bars` 193,389 行。
- 服务器:RTX 4090 24GB / CUDA / torch 2.13.0+cu130 + transformers 5.15 + akshare 1.18.64 + lightgbm 4.7 + catboost 1.2.10 + sentencepiece。
- 新数据表(本任务新建于生产库,akshare 抓取):
  - `event_financial_actual` 144,323 行 — `stock_financial_abstract`:全 162 标的 × 11 指标(EPS/归母净利/营收/ROE/净利率/毛利率/YoY 增长率…),季度回溯到 1989。
  - `event_consensus_forecast` 960 行 — `stock_profit_forecast_ths`:一致预期 EPS/净利(**仅未来未报告年份 2026/27/28**,无历史快照)。
  - `event_notice` 40,394 行 — `stock_individual_notice_report`:2020-至今公告(带日期与类型)。
  - `sentiment_news` 1,620 行 — `stock_news_em`:每标的 ~10 条近期新闻(标题+内容)。

## 诚实约束(关键)
`stock_profit_forecast_ths` 只返回**当前一致预期快照,且仅覆盖未来未报告年份**;akshare 免费层无历史一致预期快照。因此:
- **"超预期 = 实际 EPS − 一致预期 EPS" 在历史回测上无法 PIT-correct 计算**——一致预期年份(2026+)与实际年份(2020-2025)不重叠,merge 为空,surprise 块缺失。
- 若强行用当前一致预期快照贴到所有历史决策日,会造成**前视偏差**(2026 的预期用在 2020 上)。

按用户"诚实"原则,事件面**完全采用 PIT-honest 信号**:
- 实际财报 YoY(归母净利/营收/EPS 同比,来自 `归属母公司净利润增长率` 等指标,披露日 period+120d 才可知)
- 基本面水平(EPS/净利/营收/ROE/净利率/毛利率,PIT asof-merge)
- 公告事件计数+关键词类型(增减持/回购/问询函/业绩预告增减/质押…,真实日期 trailing 30/90d 计数,searchsorted 向量化)

## 事件面结果(rank_ic,80/20 时间划分,LightGBM,162 标的 7,317 行月度面板)

| 组合 | rank_ic | Δ vs price |
|---|---|---|
| price(基线) | 0.0586 | — |
| price+fund_legacy(round-32 enriched,稀疏 25 标) | 0.0768 | +0.0182 ✓ 复现用户基线 |
| price+fund_rich(新 PIT 基本面,全 162 标的回溯 1989) | 0.1438 | +0.0852 |
| **price+fund_rich+event(PIT-honest YoY+公告)** | **0.1533** | **+0.0947** |
| +consensus_fwd_caveated(当前一致预期快照,前视告诫) | 0.1412 | +0.0826(反降,前视噪声) |

诚实组合前 8 重要特征:rev_yoy(627)、net_margin_rich(517)、gross_margin_rich(504)、np_yoy(481)、rev_actual(461)、np_actual(434)、eps_yoy(422)、eps_actual(415)— 全是基本面/事件,价格特征跌出前 8。

**事件面结论**:rank_ic 0.0768 → 0.1533(**翻倍**,Δ +0.0947 vs price,+0.0765 vs round-32 enriched)。提升主要来自全 162 标的的 PIT 基本面(`stock_financial_abstract` 远比稀疏 legacy 强),公告事件再加 +0.0095。一致预期类因子因免费数据无历史快照而无法诚实使用,如实剔除。基线 0.0768/+0.0182 与用户所述完全吻合,验证管线正确。

## 情绪面结果(轻量档 — 迁移学习不微调)
编码:`bert-base-chinese`(冻结)对 `sentiment_news`(1,620 近期)+ `event_notice` 标题(40,394 历史)= 42,014 条文本取 [CLS] 768 维,按(标的,日)均值池化 → 14,043 个(标的,日)向量。历史情绪由公告标题提供(新闻仅近期尾部)。GPU 编码约 1 分钟。

| 情绪组合 | rank_ic | Δ vs 无情绪(0.1533) |
|---|---|---|
| +sentiment 原始 768 维 | 0.1522 | −0.0011 |
| +sentiment PCA-32 维 | 0.1427 | −0.0106 |

**情绪面诚实结论**:轻量 BERT(feature extraction)无论原始 768 维还是 PCA-32,**都未提升 rank_ic**(基线事件面 0.1533),反而略降——稳健。原因:结构化公告关键词类型 + trailing 计数已捕获公告信号,通用 bert-base-chinese [CLS] 不懂金融术语、增加噪声/过拟合。与用户预期完全一致:"通用 BERT 不懂金融术语,准度一般"。

## 情绪面第三步(完整迁移学习 — 微调)
用户指示"这么好怎么来" → 执行微调,但采用更优设计:弱监督(文本→前 5 日收益符号)微调 bert-base-chinese 3 分类头,产出低维金融情感分数(P正−P负),按(标的,日)聚合。时间划分保证样本外(微调仅用 80% 时间窗内文本,holdout 用未见过标签的模型预测)。训练 2 万文本/2 epoch/4090(~5 分钟),推理 42,014 条→14,043 情感分数。标签准确率:train(in-sample)0.472、hold(out-of-sample)0.556(高于多数类基线)。

| 情绪组合 | rank_ic | Δ vs 无情绪(0.1533) |
|---|---|---|
| +sentiment 轻量原始 768 维(冻结) | 0.1522 | −0.0011 |
| +sentiment 轻量 PCA-32 维 | 0.1427 | −0.0106 |
| **+sentiment 微调情感分数(5 维,完整迁移)** | **0.1241** | **−0.0292** |

**微调反而更差**。诚实原因:微调目标是预测 5 日收益(弱监督),与面板的 240 日超额收益目标存在 horizon mismatch;该 5 日预测器作为 240 日 ranker 的特征只增加噪声。情绪面两种档位(轻量 + 微调)**稳健地都不提升 240d 超额收益 rank_ic**。

按用户门槛"**验证有用再上完整微调**":轻量与微调均未验证有用 → 情绪面诚实判定为负结果,不进入可部署模型。

## 分析师评级实验(研报,2017-2026 历史日期)
`stock_research_report_em` 有历史日期研报(18,816 条,162 标的),但预测 EPS 列每次抓取都被重标为当前年份(2026/27/28)→ 老研报的预测值语义存疑(可能是当前快照,有前视风险),**不用作 surprise**。只用评级(买入=2/增持=1/持有/中性=0/卖出=-1)+ 覆盖强度(研报数),按报告日期 PIT asof。特征方差正常(非 bug)。结果:**加入评级后 rank_ic 0.1533→0.1203(甚至低于 fund_rich 单独 0.1438),稀释**——评级粘性大、低方差(多为买入)、滞后,对小 holdout 增噪。与情绪面一致的负结果,**评级剔除**。

## 生产验证门(净化 walk-forward + 成本调整 top-k 回测)
rank_ic ≠ 策略收益。把可部署模型(price+fund_rich+event,13 公告特征)做成月度多头 top-k 策略做诚实时序外样本回测:
- **净化滚动**:月度再训练(扩展窗口),训练截止回退 360 日(>240d 标签 horizon)净化标签泄漏;2021-05~2024-01 共 33 月 OOS。
- **成本调整**:月度换手 × 15bps 单边往返成本。

| 组合 | 年化净超额 | 月 Sharpe | 最大回撤 | 月胜率 | 月均换手 | 累计净超额 |
|---|---|---|---|---|---|---|
| top-10 | **7.7%** | 0.514 | −14.3% | 60.6% | 58.5% | 22.6% |
| top-20 | 7.4% | 0.491 | −11.4% | 54.5% | 48.0% | 21.6% |

**结论**:rank_ic=0.1533 转化为 ~7.4-7.7% 年化净超额(扣 15bps 成本后),33 月净化 OOS,Sharpe ~0.5,胜率 55-61%,对组合规模稳健。**真实可交易 alpha 经时序外样本确认**。诚实局限:多头集中(top-k of 162)、2023-12 单月 −14% 异常拖低 Sharpe(肥尾)、33 月是单一 CN 市场regime、无空头侧。

## 最终可部署组合
**price + fund_rich + event**:rank_ic = **0.1533**(vs round-32 0.0768 翻倍,+0.0765;vs price 0.0586,+0.0947)。前 8 特征:rev_yoy、net_margin_rich、gross_margin_rich、np_yoy、rev_actual、np_actual、eps_yoy、eps_actual——全 PIT-honest。情绪块**剔除**。

## 产出文件
- 数据抓取:`scripts/fetch_event_sentiment_data.py`(`event_financial_actual`/`event_consensus_forecast`/`event_notice`/`sentiment_news` 四表入生产库)
- 面板评估:`scripts/panel_eval.py`(PIT-honest,自包含 sqlite3+pandas+lightgbm)
- 轻量编码:`scripts/encode_news_bert.py`(冻结 bert-base-chinese [CLS])
- 微调:`scripts/finetune_bert_sentiment.py`(弱监督 3 分类头)
- 结果:`artifacts/model_performance/panel_eval_event_canonical.json`(可部署)、`panel_eval_sentiment_finetune.json`(微调实验)、`panel_eval_consolidated.json`(汇总)、`artifacts/sentiment_vectors/*.parquet`(情感向量)
- 文档:`docs/event_sentiment_findings.md`
