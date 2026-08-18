# 当前系统事实源（2026-08）

这是 A 股长期投资研究主线的唯一当前说明。旧的四市场、`0700.HK` 演示、
`approved` 正式发布和同步训练描述均为历史/规划材料，不代表当前能力。

当前数据缺口与阻断状态见 [`current-data-gaps.md`](current-data-gaps.md)。
完整的训练前置条件汇总可用 `scripts/audit_long_term_readiness.py` 生成；该报告只读，
不会切换 active 指针。

## 当前边界

- 主线：CN A 股股票池与 ETF 参考，研究级公开数据。
- 数据层：`raw -> standard -> pit`；下载目录不能被训练读取。
- 数据等级：`research_pit`，未经完整门禁始终 `research_only`、
  `deployment_ready=false`。
- 任务：`config/long_term_training.yaml` 的 `primary_targets` 固定为
  `excess_return_120d`、`excess_return_240d`、`future_max_drawdown_120d` 和
  `future_max_drawdown_240d` 四个长期模型任务；`auxiliary_targets` 的基本面质量持续性只作为辅助任务或独立证据层；
  旧的 1/5/20 日绝对方向/绝对收益任务只能作为短周期研究，不得在用户界面称为长期结论。
- 5/20 日超额收益由 `scripts/run_panel_research_training.py` 作为辅助横截面研究任务维护；
  `scripts/run_long_term_training.py` 的当前长期主合同固定为 120/240 日超额收益与 120/240 日最大回撤四项任务。季度级质量持续性只能作为独立基本面评分卡或候选实验，不能替换四项主任务。
- 长期样本至少需要 1,260 个交易日历史，且 purge/embargo 按季度决策期计数；不足时训练直接阻断。
- 宏观数据先经过 `scripts/build_cn_macro_pit.py` 归一化；只有发布日期与可用时间被证明后，
  `rebuild_cn_research_pit.py` 才会把宏观特征前向填充到样本，目前公开源缺少发布日期，宏观特征保持阻断。
- `rebuild_cn_research_pit.py` 生成市场宽度时必须读取 PIT 历史成员映射；当前 cohort 只能通过
  明确的 `--allow-current-cohort-breadth` 测试开关使用，生产重建没有默认回退。
- 训练入口：`scripts/run_long_term_training.py`。它要求 active 快照、完整层级、
  PIT 时间覆盖、成熟标签和门禁通过；否则只写 blocked 报告。
- `scripts/audit_long_term_readiness.py` 会在读取 active 指针时重新核对快照内每个文件的
  存在性、大小、SHA-256 和内容审计计数，并复跑长期快照硬门禁；active 指针存在本身不等于可训练。
  同一审计还要求训练报告引用存在且 hash 一致的压缩 Parquet 预测文件，并逐个核对四项长期模型评估合同字段；旧评估文件缺少字段时只标记 `not_recorded` 并阻断 readiness，不用默认值补齐。
  PIT 泄漏门禁同样不接受默认的零值：active manifest 必须声明带 SHA-256 的泄漏审计文件和显式错误计数，
  readiness 会重新读取文件并核对计数；缺少证据、文件不存在或 hash 不一致时保持 blocked。
- 辅助的表格、序列和面板研究入口也要求 `--data-root` 下存在有效 active 指针并复跑
  `config/long_term_training.yaml` 的快照门禁（显式 `--allow-research-only` 才能降级），
  且每个样本 manifest 必须带 `data_snapshot_id` 与
  `data_snapshot_manifest_hash`；缺少绑定时拒绝读取。派生 Parquet 可以放在
  独立的内容寻址存储中，但不能位于 `landing`，并必须由该绑定 manifest 引用。
- `scripts/rebuild_cn_research_pit.py` 默认按真实 `available_at` 建立财报可见性；只有明确传入
  `--allow-unproven-visibility` 才会启用研究兼容模式，且产物仍标记 `research_only`。
- API 只负责提交和查询 Job；`scripts/run_research_worker.py` 负责分钟级调度/采集，
  `scripts/run_training_worker.py` 独立领取长期训练 Job。训练 worker 使用独占锁和
  24 小时超时，API 与调度器都不会在进程内同步执行长期训练。
- CI 在运行完整 Python/前端测试外，还执行 `compileall` 和无数据写入的
  `run_cn_research_demo.py --dry-run`；正式 readiness 审计仍保留为数据完成后的只读门禁，
  不会因当前下载尚未完成而被 CI 误判为通过。
- 长期候选更换还必须经过 `scripts/evaluate_long_term_promotion.py`：成本后留出表现、
  Rank IC 和至少 60 个独立有效 Shadow 交易日同时满足，否则维持 `research_only`。
- 长期 scorecard（经营质量、成长稳定性、估值位置、股东回报、风险和证据完整度）
  由 `run_long_term_training.py` 产出并通过只读 `/api/v1/research-scorecards/latest`
  提供给前端；报告阻断或维度缺失时显示不可用，不用默认值补齐。
- 首页以数据日期、结果状态和长期 scorecard 为主流程；120/240 日四项模型读数直接展示，1/5/20 日读数只放在默认折叠的
  “短期市场观察”中，技术与审计抽屉不再重复渲染长期研究面板。
- 长期研究 Agent 使用独立的只读序列：PIT 取证、长期 scorecard、四项长期模型读数、数据截止时间与来源状态、
  支持/反方证据、质量门禁。scorecard 缺失、证据完整度不足或来源 hash 无法核验时必须
  `abstain`；四项模型读数任一缺失时同样 `abstain`，禁止使用短周期预测替代长期结论。
- 长期研究解释固定包含适用周期、当前可说内容、理由、反方证据、主要风险、观察条件、
  推翻条件和数据截止时间；最终文本还要通过版本化合规规则，拦截个股买卖、仓位、目标价
  和保证收益表达，拦截记录写入 Agent 审计事件。
- 金融知识库支持长期研究事实卡，区分 `supporting`、`contrary` 与 `uncertain`，并保存
  PIT 时间、有效期、修订链、来源和权威等级。查询无结果默认表示未知；只有
  PIT 覆盖台账明确 `confirmed_none` 时，才能解释为已确认没有对应事件。
- `run_cn_research_inference.py` 的 `--decision-time` 是历史回放和 Shadow 重演的唯一 PIT cutoff；
  未传入时才使用当前 UTC 时间。样本、参考价格和序列 challenger 都必须不晚于该 cutoff，
  缺少 `available_at` 的价格只能降级/弃答，不能回退到最新文件行。
- 四项长期深度模型由 `config/long_term_deep_model_roster.json` 登记，
  `investment_research.service.deep_long_term.DeepLongTermInferenceService` 只读加载并校验
  `.pt`、评估报告、feature order、normalizer（并与 checkpoint 内嵌统计量逐特征比对）、snapshot 和 SHA-256；输出 q10/q50/q90
  模型观察；独立头发生分位数交叉时记录 `quantile_projection=monotone_sort`，不穿透旧的表格模型推理路径。评分卡可通过 `long_term_model_readings` 字段携带
  四项读数，Agent 只解释这些结构化结果，不将其合并为交易指令。生产接入应调用
  `write_long_term_model_readings` 或 `predict_all_and_persist`，将四项读数按标的写入独立的
  `artifacts/long_term_model_readings/latest.json`；写入前校验四任务齐全、单一 snapshot、
  q10≤q50≤q90、模型状态和来源字段，文件采用原子替换。Scorecard/API 优先读取该独立 artifact，
  只有旧报告没有独立文件时才兼容读取内嵌字段。
- 已下载的深度模型还必须先由 `scripts/register_long_term_model_artifacts.py` 生成
  `artifacts/long_term_model_registry/latest.json`。该清单只登记现有文件引用和 SHA-256，
  记录四项任务、模型/评估/feature order/normalizer、dataset/snapshot/fold hash、输入窗口、
  训练样本数量和训练年份范围；明确标记 `registered_research_only`，不会复制模型或创建生产模型。
  若源评估只记录年份过滤而没有日级起止日期，清单保留 `granularity=year` 和缺失原因，不自行推断精确日期。
- `/api/v1/research-scorecards/latest` 同时返回只读的四模型评估摘要：训练标的/日期数量、窗口与特征数、
  PIT 层级、snapshot/dataset/model/report/fold 哈希、留出/压力指标和 Shadow 状态。前端只在默认折叠的
  “专业详情”中展示这些字段，普通用户层不展示复杂评估指标。

## 迁移规则

1. 下载完成后先在 `landing/<download_run_id>` 生成 manifest，记录成功/失败/降级数量、
   Provider、文件路径、SHA-256、日期/行数、发布时间/修订覆盖率和缺失原因，并完成 hash、Schema、
   证券生命周期、交易状态、OHLC、复权一致性、重复值、交易日、文件引用和 PIT 审计。
   下载输出审计会在 landing 前检查事件缺失语义；事件 `complete` 记录只有在同时带有
   `missing_reason_code=no_events_confirmed` 和明确的 `missing_reason=no_events_confirmed`
   时，才能表示 Provider 已确认没有事件；其他 `complete` 记录不得带 missing reason。
   未带明确代码的“没有事件”或 Provider 缺口保持 blocked。
   同时将 PIT 泄漏审计文件的引用、SHA-256 和错误计数写入 manifest；不能以未提供审计的默认 `0` 通过训练门禁。
   `collected_at_coverage` 也必须来自下载记录；缺失时保持未知，不再由快照构建脚本默认填成 100%。
2. 通过校验后原子提升到 `snapshots/<snapshot_id>`，再交换 `active.json`。
3. 训练配置、数据快照、特征合同、标签版本和模型版本分别哈希；数据修订使用
   增量失效计划，只重建受影响标的和日期范围：滚动特征向修订日之后扩展
   lookback，前向标签向修订日前回溯最长 horizon；下游 hash 和引用必须重新校验。
4. 任何事件缺口必须区分“确认没有事件”“Provider 未覆盖”“发布时间不可验证”
   和“源字段缺失”，不能用 0 代替未知。

评估逐行预测统一写入 zstd 压缩 Parquet，JSON 只保留指标和引用；
`scripts/index_training_artifacts.py` 会扫描本地 `*_ref`/`ref` 引用并在悬空、缺失或
hash 不一致时阻断。`scripts/prune_training_artifacts.py` 会同时检查反向引用，
只清理未被任何报告引用且已过保留期的文件；`rebuild_required` 产物默认保留，
便于回放和增量重建，必须显式传入 `--include-rebuild-required` 才允许清理。

`docs/demo-script.md`、`docs/model-research-report.md` 和 `docs/four-market-pit-release.md`
保留作历史/规划参考，不得作为当前产品事实源。
