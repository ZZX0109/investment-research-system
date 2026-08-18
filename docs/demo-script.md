# 青云计划演示脚本

# 历史演示脚本（非当前产品事实源）

> 本文保留用于历史回放。`0700.HK`、同步训练、`approved` 模型和正式发布描述不代表当前 A 股长期投资主线；当前边界请以 [`current-system.md`](current-system.md) 为准。

固定资产为 `0700.HK`，正式模式为 real。登录后选择腾讯控股，触发真实数据刷新并展示 provider、抓取时间、缓存与 hash。创建 `single_asset_risk_research` AgentRun，状态图依次显示任务分类、受控计划、证据收集、29 维特征、approved 模型、反方证据和自审计。打开 Evidence/Claim 关系，确认公告和新闻均早于 as-of。展示 RF primary 与 linear fallback 的风险差异、历史相似情景分布和组合影响。随后注入一条发布时间缺失或相互冲突的证据，重新运行并展示 gate 从 pass/warn 降为 hold/block，Agent abstain 且不输出买卖动作。最后回放第一次固定 ResearchRun，确认来源 revision、模型版本、报告 hash 与原结论保持不变。

多模态部分运行 `python3 scripts/run_multimodal_experiment.py`，展示腾讯 2024 年报第 4 页收入趋势和第 133 页现金流量表的标注区域、页码、单位、数字与失败拒答。模型研究部分打开 `docs/model-research-report.md`，重点说明 RF 的 paired-fold 增益、高波动校准限制、reference/full 消融没有正增益，以及为什么研究结论不能绕过 strict gate。
