# 投研数据源与资源矩阵

本项目把公开资源作为研究级输入，不把开源接口直接等同于正式授权数据。每个适配器必须保留原始响应、请求时间、来源 URL、字段映射、授权范围、失败原因和质量状态。

| 数据域 | 首选来源 | 开源/工程资源 | 接入策略 | 正式版要求 |
|---|---|---|---|---|
| A 股/ETF 行情 | SSE、SZSE、交易所授权行情 | [AKShare](https://github.com/akfamily/akshare)、[BaoStock](https://www.baostock.com/)、[A-share 多源兜底示例](https://github.com/shouldnotappearcalm/a-share-skill/blob/main/a-share-data/scripts/fetch_history_fallback.py)、[TDX day-file API](https://github.com/swRains/tdx_api)、[北交所新旧代码对照表](https://www.bse.cn/service/code_mapping.html) | Yahoo chart raw/qfq 优先，新浪 raw + 腾讯 qfq、AKShare/BaoStock 备用；北交所 raw 用官方 TDX `.day` 包，920 代码用官方新旧代码表衔接历史身份，前复权仅接收可验证的公开/授权响应；OHLC/交易日/哈希审计，失败逐条入账 | 授权行情、复权因子和历史修订协议；北交所行情另须取得其许可 |
| 财务/公告 | [巨潮资讯网](https://www.cninfo.com.cn/)、上交所、深交所 | [TuShare](https://github.com/waditu/tushare)、[东方财富数据中心](https://datacenter-web.eastmoney.com/) | 巨潮提供公告披露证据；东方财富按报告期 landing 利润表、现金流、资产负债表和业绩快报，逐页保留哈希后再与巨潮按证券/报告期对齐 | 公告正文、逐项修订链、正式可用时间和商业展示授权 |
| 指数/行业成分 | [中证指数](https://www.csindex.com.cn/)、交易所指数页面 | [ZVT CSI 接口示例](https://github.com/zvtvz/zvt/blob/master/src/zvt/recorders/exchange/api/cs_index_stock_api.py) | 保存成分公告、实施日、effective_from/effective_to；禁止当前池回填历史 | 完整调入/调出事件链和授权历史面板 |
| 宏观 | [国家统计局](https://www.stats.gov.cn/)、[人民银行](https://www.pbc.gov.cn/)、中国外汇交易中心 | AKShare 宏观接口、SHIBOR/汇率历史公开端点 | 观察期、计划发布日期、实际发布日期、首次发布值、修订版本分开保存；央行/CFETS 补充证据记录证据等级和时间精度 | 实际发布日期和修订链 100% |
| 融资融券/市场状态 | 沪深交易所、授权供应商 | AKShare、BaoStock | 市场级数据不得伪造证券代码；来源冲突进入人工校验 | 交易状态发布时间和历史停复牌证明 |
| 商业数据 | Wind、Choice、iFinD、Tushare Pro | 不以开源镜像替代 | 适配器只允许在 license_scope 允许的租户/导出范围内启用 | 数据 SLA、导出授权、审计与租户隔离 |

授权文件进入系统前统一经过 [`ingest_authorized_pit_source.py`](../scripts/ingest_authorized_pit_source.py)。它要求供应商授权声明、历史 `available_at`、公告发布时间和修订链能力，并把输入写入 content-addressed landing；该步骤本身不会激活快照。

## 资源使用规则

1. AKShare、BaoStock、TuShare 等仅作为 provider adapter，不直接作为 PIT 证明。
2. GitHub 代码可用于接口适配、字段映射和重试机制；原始金融数据的版权、授权和展示边界必须单独核验。
3. 每个 provider 需要配置 `source_uri`、`license_scope`、`coverage_start/end`、`published_at` 语义和备用 provider。
4. 不能确认发布时间、修订版本或历史有效区间时，记录 `missing_reason_code` 并降级为 `research_only`。
5. 开源接口异常时保留旧快照，不覆盖可用版本；重试结果通过哈希和 manifest 重新验收。

## 当前项目落地资源

- [下载覆盖清单](../artifacts/download_manifests/latest.json)
- [当前全 A 股/ETF 证券枚举](../artifacts/cn_security_master_universe/latest.json)
- [全市场公开上市/退市/更名生命周期回补](../artifacts/cn_security_lifecycle_full/latest.json)
- [全量已下载 raw 行情标准层重建](../artifacts/free_research_rebuild_all_raw_standard/latest.json)
- [当前全市场行情回补分片账本](../artifacts/free_research_coverage_shard_test.json)
- [并行 BaoStock 回补验证账本](../artifacts/free_research_coverage_parallel_test.json)
- [全市场公开 raw 行情回补账本](../artifacts/free_research_coverage_public_raw_merged.json)
- [全市场公开 qfq 行情回补账本](../artifacts/free_research_coverage_public_qfq_merged.json)
- [通达信北交所 raw 行情回补账本](../artifacts/free_research_coverage_tdx_bj_raw.json)
- [北交所官方新旧代码映射](../artifacts/cn_bse_code_mapping/latest.json)
- [全市场公开多源行情合并账本](../artifacts/free_research_coverage_public_merged.json)
- [国家统计局实际发布日期抓取结果](../artifacts/cn_macro_actual_release_nbs/latest.json)
- [央行/CFETS/SHIBOR 宏观历史发布时间补充证据](../artifacts/subagent_macro_history_retry/latest.json)
- [统一宏观 PIT 审计](../artifacts/cn_research_auxiliary/macro_pit_latest.json)
- [全市场核心财报 landing 审计](../artifacts/cn_financial_reports_eastmoney/performance-audit.json)
- [全市场财报规范化导入预检](../artifacts/cn_financial_eastmoney_import/latest.json)
- [项目缺失矩阵](../artifacts/project_completion/latest.json)
- [全市场数据完成计划](../artifacts/cn_data_completion_plan/latest.json)
- [全市场数据完成审计](../artifacts/cn_data_completion_audit/latest.json)
- [全项目优化交付清单](../artifacts/optimization_delivery/latest.json)
- [数据隔离报告](../artifacts/data_quarantine/latest.json)
- [长期模型就绪度](../artifacts/long_term_readiness/latest.json)
- [候选模型评估契约](../artifacts/long_term_training/candidate-suite/evaluation-contract.json)
- [授权 PIT 接入说明](authorized-pit-intake.md)
