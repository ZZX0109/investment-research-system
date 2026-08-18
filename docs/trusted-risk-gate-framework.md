# 可信风险门禁框架

> 历史/通用门禁设计。当前产品不把任何模型标为 approved 或 deployment-ready；A 股长期主线请以 [`current-system.md`](current-system.md) 和 [`current-data-gaps.md`](current-data-gaps.md) 为准。

系统输出的是个人投研中的风险研究信号，而非交易指令。一个结论必须同时经过四层：数据层确认来源、时间与 PIT 完整性；模型层生成校准后的回撤风险概率；审批层按市场、regime、近端窗口和模型状态决定是否可用；交付层把预测、证据、Judge 与报告固定在同一个 ResearchRun 快照中。

门禁优先于模型分数：来源缺失、数据过期、证据不足、特征覆盖不足或模型未批准时，Judge 会输出 WARN、HOLD 或 BLOCK，并保留原因。历史报告仅回放对应 run 的冻结输入、模型版本和 Judge 结果。

正式模型仅包括 approved 的 random-forest 与 linear-baseline 回退。PatchTST、TCN、iTransformer 是 research-only challenger，不参与线上结论。
