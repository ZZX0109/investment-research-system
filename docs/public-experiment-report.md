# 公开实验报告

> 历史实验记录（多市场、旧快照）。不代表当前 A 股长期投资训练或发布状态；当前事实源见 [`current-system.md`](current-system.md)。

- 训练运行：`20260713T083502Z-real-full`
- 样本快照：`0af23f5133dc31a1fc2cec7e58a6ffaf72f65e09de837ef84f1de91f79b3b29c`
- 特征合同：`investment-risk-features-v1`
- 数据模式：`real`；随机种子：`42`
- 纳入市场：cn, hk, jp, us

## 验证与限制

审批只使用时间序列 walk-forward/Purged CV 配置，不使用随机切分。PIT 审计、provider 覆盖、缺失率、股票池与市场排除原因均见同目录 manifest。股票池是版本化 coverage preset，不声称消除幸存者偏差；退市、停牌和 provider 缺失均是当前限制。

## 主模型

`random-forest`：AUROC `0.7487`，ECE `0.0972`，Brier `0.1944`，风险桶 precision `0.6888`。未获批模型保持 research-only；失败与门禁原因来自 evaluation/task matrix。
