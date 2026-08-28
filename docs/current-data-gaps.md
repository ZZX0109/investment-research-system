# 当前数据缺口报告（2026-08-25，按 2026-08-26 现场复核）

事实源：[`artifacts/project_completion/latest.json`](../artifacts/project_completion/latest.json)、[`artifacts/cn_data_completion_plan/latest.json`](../artifacts/cn_data_completion_plan/latest.json)、[`artifacts/download_manifests/latest.json`](../artifacts/download_manifests/latest.json) 和 [`artifacts/long_term_readiness/latest.json`](../artifacts/long_term_readiness/latest.json)。这些文件由只读审计脚本生成，下载 raw 目录和已有 active 数据不会被此报告覆盖。

当前状态为 `blocked`，项目完成度为 **13/17**，数据完成计划为 **11/20**；没有 `var/cn-research/active.json`，因此长期训练和正式发布不会启动。当前发布通道为 `research_only`。

已发现并完成 SHA-256 引用核验的主要数据集包括行情、复权因子、财报、证券/行业主数据、公司行为、事件、融资、宏观、市场宽度和 PIT 时间记录；但“发现”不等于 PIT 可用。

必须先处理：

- `cn_trading_status` 已从标准行情形成 1,185,427 条独立记录，但历史发布时间未独立证明，仍为 `degraded`，不能作为完整 PIT 数据集。
- 市场宽度旧产物已标记阻断：历史指数/行业成员仍缺少完整的 `effective_at/available_at` 区间，不能用当前固定股票池套用历史。
- 事件数据仍是滚动公开窗口，历史发布时间/可用时间不完整；不能把缺口填成无事件。
  只有 `missing_reason_code=no_events_confirmed` 且明确写明 `missing_reason=no_events_confirmed`
  才能表示 Provider 已确认没有事件；其他 complete 记录携带缺失原因仍会阻断审计。
- 研究目标行业映射和全市场当前公司行业映射均为 **5,549/5,549（100%）**；这只证明当前行业映射，不等于历史行业成员生效区间已证明。
- 当前证券枚举为 **5,554** 个 A 股/ETF，追加式目录 raw/qfq 均覆盖 **5,554/5,554**。生命周期合并产物覆盖 5,223 个历史股票记录：上市日期、ST、上市状态约 99.66%，已知退市记录日期 100%；代码迁移事件覆盖约 4.75% 的全体记录，但已落地的 248 个代码迁移记录完整率为 100%。这些是研究级记录完整度，不是全历史生命周期证明。详见 [`artifacts/cn_security_master_universe/latest.json`](../artifacts/cn_security_master_universe/latest.json)、[`artifacts/cn_security_lifecycle_full/latest.json`](../artifacts/cn_security_lifecycle_full/latest.json) 与 [`artifacts/cn_security_master/latest.json`](../artifacts/cn_security_master/latest.json)。
- 财务核心字段覆盖率为 **97.46%**，低于 98% 门槛；`quick_ratio/cash_ratio` 等字段仍有缺口，且 `pit_verified=false`。最近的公开 Eastmoney 指标回补新增了 367 条 research-only balance 记录，但没有改变正式 PIT 状态。当前 coverage artifact 记录 **5,509 个股票、418,061 条公告证据**，发布时间字段覆盖 100%，但公告证据不是数值基本面本身；公告到报告期的总体匹配约 68.87%，主基本面池约 99.40%，修订链和 provider 级 `available_at` 仍未验证。详见 [`artifacts/cn_financial_coverage/latest.json`](../artifacts/cn_financial_coverage/latest.json)。
  当前 Eastmoney balance landing 的诊断显示货币资金覆盖 99.50%、存货覆盖 96.04%，但 `CURRENT_ASSETS` 与 `CURRENT_LIABILITIES` 均为 0%，因此速动比率和现金比率没有合法推导路径；详见 [`artifacts/cn_financial_ratios_akshare/derived_landing.json`](../artifacts/cn_financial_ratios_akshare/derived_landing.json)。系统不使用合成值填充。
- 宏观数据统一观察期记录为 5,897 条；最近重跑官方 NBS 文章抓取并重新合并后，带 `published_at` 的记录覆盖率为 **59.96%**，其中 1,536 条只有日期级证据、825 条仍未解析。由于 CPI/PPI/PMI 与 LPR 仍未形成完整可用时间和修订链， [`artifacts/cn_research_auxiliary/macro_pit_latest.json`](../artifacts/cn_research_auxiliary/macro_pit_latest.json) 仍为 `degraded`，不能作为完整历史 PIT 特征。
- 长期快照还必须声明关键财务字段目标数/观测数，当前没有该门禁证据时默认阻断。
- 四项已登记深度模型的旧评估文件没有完整持久化 Rank ICIR、分年度/行业/市场状态和数据覆盖分层、成本后回撤、换手与容量字段；readiness 现在逐任务列出 `not_recorded` 字段，不会把未记录解释为 0。
- 长期训练报告必须引用 zstd Parquet 预测文件并提供匹配 SHA-256；报告缺少引用或文件 hash 不一致时，`training_prediction_parquet` 门禁阻断。
- 四项候选模型已经生成独立的 `suite-report.json` 和 `evaluation-contract.json`；其中容量、年度/行业/状态稳定性和完整性分层等未记录字段保持 `not_recorded`，候选集继续标记为 `research_only`，不得直接进入 active 或生产 Agent。
- Shadow 已有 60 个独立有效交易日，但真实预测只覆盖 **2/60 个交易日（3.33%）**；另有 2,419 条空预测/拒答记录。60 日门槛不能解读为 60 日真实模型预测完成，详情见 [`artifacts/research_shadow/summary.json`](../artifacts/research_shadow/summary.json)。
- 当前全市场标准层已有 346 个标准 manifest；2026-08-21 research snapshot 已完成 191 股票 + 5 ETF 的样本绑定，共 4,390 个 manifest、1,024,803 行，分区审计无错误，四个长期标签覆盖分别为 56.55%、54.32%、93.92%、91.68%。该层已可作为 Research-only baseline 输入，但仍不等于正式 PIT 或生产训练资格。样本生成通过 `scripts/run_cn_research_sample_batches.py`（可断点运行）、`scripts/adopt_cn_research_sample_staging.py`（仅迁移已校验的旧 staging marker）与 `scripts/merge_cn_research_sample_batches.py`（校验快照、重复分区和完整标的后才允许更新 latest）完成。
- 统一长期训练入口为 `scripts/run_long_term_automation.py`；当前可执行只读 `--mode dry-run`，会生成 readiness、阶段计划和阻断原因，不生成模型权重、预测文件，也不会修改 `active.json`。`--mode formal` 只有 active 快照、绑定样本清单和 PIT 门禁全部通过后才会启动。
- 授权数据接入边界已落地为 `scripts/ingest_authorized_pit_source.py`；它严格校验 `published_at/available_at`、修订链、SHA-256 和授权声明，生成 content-addressed landing manifest，但固定保持 `active_snapshot_eligible=false`，不会绕过后续快照与泄漏审计。

只有完整数据落入独立 `landing/<download_run_id>`，通过 hash、Schema、代码、交易日、重复值、OHLC、复权一致性、交易状态、PIT 和文件引用审计，并补齐 raw/standard/pit 三层后，才允许原子切换 active 指针。

可执行的全市场数据完成计划见 [`artifacts/cn_data_completion_plan/latest.json`](../artifacts/cn_data_completion_plan/latest.json)，计划由 [`scripts/run_cn_data_completion.py`](../scripts/run_cn_data_completion.py) 生成；默认只读，执行网络回补必须显式指定 `--execute --step <id>`，不会意外启动全市场长任务或写入 active 指针。

财务公告回补按证券逐条写入 `progress.json`，中断后会从最后一个已持久化证券继续；状态证据和更名/ST 证据也支持 `--all-current-universe`，不再默认退回 167 个演示标的。

全项目交付状态由 [`artifacts/optimization_delivery/latest.json`](../artifacts/optimization_delivery/latest.json) 汇总，包含数据、PIT、模型、Shadow、Agent、前端和正式发布通道；当前发布通道明确为 `research_only`。
