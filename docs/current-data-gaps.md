# 当前数据缺口报告（2026-08-18）

事实源：[`artifacts/download_manifests/latest.json`](../artifacts/download_manifests/latest.json)。该文件由只读审计脚本生成，下载 raw 目录和已有 active 数据不会被此报告覆盖。

当前状态为 `blocked`，没有 `var/cn-research/active.json`，因此长期训练不会启动。

已发现并完成 SHA-256 引用核验的主要数据集包括行情、复权因子、财报、证券/行业主数据、公司行为、事件、融资、宏观、市场宽度和 PIT 时间记录；但“发现”不等于 PIT 可用。

必须先处理：

- `cn_trading_status` 已从标准行情形成 1,185,427 条独立记录，但历史发布时间未独立证明，仍为 `degraded`，不能作为完整 PIT 数据集。
- 市场宽度旧产物已标记阻断：此前使用当前固定股票池套用历史，必须补齐带有效期和可用时间的历史股票池成员后重建。
- 事件数据仍是滚动公开窗口，历史发布时间/可用时间不完整；不能把缺口填成无事件。
  只有 `missing_reason_code=no_events_confirmed` 且明确写明 `missing_reason=no_events_confirmed`
  才能表示 Provider 已确认没有事件；其他 complete 记录携带缺失原因仍会阻断审计。
- 行业映射目前约 165/167（以最新构建报告为准），需达到训练门禁的 98%。
- 已生成 219 个标的的观测证券主数据和历史成员关系，但 ST、退市、代码变更及历史有效时间覆盖为 0，仍不能消除幸存者偏差。
- 财报字段仍需按关键指标覆盖率、公告时间、单季/累计口径、单位和修订版本逐字段验收。
- 已生成财报逐字段审计：当前训练所需 22 个关键字段在已声明的 4,809 个公司-报告期单元中覆盖 103,364/105,798（97.70%）；`gpMargin`、存货周转率、流动/速动/现金比率、经营现金流/净利润等字段低于 95%。公告日期虽存在，但 `available_at` 仍是采集时间，PIT 可用时间未证明，因此报告仍为 degraded。详见 [`artifacts/cn_financial_coverage/latest.json`](../artifacts/cn_financial_coverage/latest.json)。
- 宏观数据已生成统一观察期记录（5,897 条），但公开源没有可核验发布日期，`published_at_coverage=0`，因此 [`artifacts/cn_research_auxiliary/macro_pit_latest.json`](../artifacts/cn_research_auxiliary/macro_pit_latest.json) 保持 degraded，不能直接作为历史特征。
- 长期快照还必须声明关键财务字段目标数/观测数，当前没有该门禁证据时默认阻断。
- 四项已登记深度模型的旧评估文件没有完整持久化 Rank ICIR、分年度/行业/市场状态和数据覆盖分层、成本后回撤、换手与容量字段；readiness 现在逐任务列出 `not_recorded` 字段，不会把未记录解释为 0。
- 长期训练报告必须引用 zstd Parquet 预测文件并提供匹配 SHA-256；报告缺少引用或文件 hash 不一致时，`training_prediction_parquet` 门禁阻断。

只有完整数据落入独立 `landing/<download_run_id>`，通过 hash、Schema、代码、交易日、重复值、OHLC、复权一致性、交易状态、PIT 和文件引用审计，并补齐 raw/standard/pit 三层后，才允许原子切换 active 指针。
