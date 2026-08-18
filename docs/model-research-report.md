# 模型研究报告

## 研究边界

# 历史模型研究报告（非当前长期训练结论）

> 本文记录旧的短周期回撤实验。报告中的 20 日标签、样本规模和 `approved` 语义不代表当前 A 股长期投资主线；当前训练合同请以 [`current-system.md`](current-system.md) 和 `config/long_term_training.yaml` 为准。

本报告只研究未来 20 个交易日显著回撤风险门禁。训练路径为 `real + full + walk-forward`，覆盖 128 个标的和 149,876 个样本。收益、风险调整收益、波动率突增和事件后回撤属于辅助任务，不参与 approved 判定。

## RF 与线性 Champion

RF 的总体 AUROC 为 0.7487，线性基线为 0.6825；RF 的 ECE 为 0.0972，Brier 为 0.1944，风险桶 lift 为 0.0465。RF 已通过当前 overall、market、coverage group、regime 和 recent-window 门禁。配对 fold 差异及 95% block-bootstrap 区间见 `audits/model_research_findings.json`。

## 适用条件

RF 在总体审批下为 **eligible**。高波动 regime 中 AUROC 和 Brier 优于 champion，但 ECE 略高，因此标记 **conditional**。事件特征相对 price-only 的 AUROC 增量为 0.0032，可保留；reference-only 增量为 -0.0026，full 增量为 -0.0004，两者没有稳定超越 price-only，部署中应保留覆盖门禁与 fallback，不把特征数量当成有效性证据。

## 校准、缺失与 Abstention

RF 当前使用 isotonic 校准，严格审批结果来自 44 个时间滚动 fold。本轮已保存逐行 OOF 预测并计算 50%/60%/75%/85%/95% abstention 曲线。以 75% 置信阈值为例，保留 67,412 条预测，abstention rate 为 74.01%，保留样本准确率为 85.91%。特征覆盖率分桶的错误率和 Brier 见 `audits/missingness_sensitivity.json`。

## Paper Validation

历史时间外回放中，RF AUROC 为 0.7487，alert precision 为 0.6888，drawdown lift 为 0.0465。未来观测只在到期后回填，且不会自动覆盖 approved 模型。

## 结论

RF 在当前真实数据、当前特征合同与严格 gate 下可以作为 primary，linear-baseline 继续作为 champion fallback。reference/full 消融没有提供正增益，高波动校准仍是主要限制；这些条件必须随模型版本一起展示。
