# 投研模型优化路线与实验说明

> 本文保留为历史/规划参考。当前主线已转为 A 股 60/120/240 日长期横截面任务，旧 20 日实验不能替代长期训练结论；当前事实源见 [`current-system.md`](current-system.md)。

## 一句话结论

当前系统已经完成 PIT V4.1 重建、162 只股票 + 5 只 ETF 的研究数据骨架，以及第一轮深度序列模型实验；但现阶段结果仍是 research-only，不能称为高精度或可部署模型。方向任务的准确率接近随机基线，说明下一阶段的重点不是继续堆训练轮数，而是改成横截面选股目标、扩大股票池、补齐可用信息集，并用严格的时间外推和交易成本后的组合表现判断是否真的有投资价值。

## 当前实验结果如何解释

最近一轮 `auto-v43c-20260815` 的 20 个阶段均完成，失败阶段为 0，但部署闸门仍未通过。代表性结果：

- `direction_1d`：PatchTST holdout accuracy 约 36.2%，balanced accuracy 约 34.3%，macro AUROC 约 0.525。
- `direction_5d`：PatchTST holdout accuracy 约 37.2%，balanced accuracy 约 37.2%，macro AUROC 约 0.550。
- `return_20d`：TCN 的 holdout P50 MAE 约 0.0845，是当轮回归模型中较低的一项。
- `drawdown_20d`：iTransformer 的 holdout Brier 约 0.1825，是当轮风险模型中较低的一项。

这些数字只能说明“代码、数据和验证链路能跑通”。它们没有证明稳定的 alpha：方向准确率没有明显超过可交易基线，回归误差也没有直接转换成成本后的组合收益。当前结果应作为基线和失败证据保存，而不是作为产品宣传数字。

## 为什么准确率上不去

1. **标签和目标不匹配。** 预测绝对涨跌方向会把市场共同波动、行业轮动和个股 alpha 混在一起；投资研究真正关心的是同一交易日哪些股票相对更强，以及扣除交易成本后能否形成组合收益。
2. **金融信号噪声很高。** 股票收益的可预测部分通常很小，模型容量越大不一定越好；非线性和特征交互重要，但必须配合严格的时间外推验证。
3. **样本有效数量没有想象中大。** 许多日期来自相同市场状态，相邻窗口高度相关；扩大 epoch 或随机切分不能创造新的独立信息。
4. **单股票序列模型缺少横截面上下文。** 仅编码一只股票的时间窗口，无法充分利用市场、行业、ETF 和股票之间的相对关系。
5. **信息覆盖和发布时间仍是约束。** 财报、事件、宏观数据必须按 `available_at` 进入样本；缺失不能直接当作“没有事件”。特征存在于代码不等于 162+5 个标的、每个历史时期都有效覆盖。
6. **模型选择本身可能过拟合。** 多模型、多窗口、多种标签、多次试验后挑最好结果，会产生回测选择偏差，因此最终测试集必须冻结，候选数量和选择过程也要记录。

## 本阶段已经落地的目标改造

- 新增 `excess_return_5d` 和 `excess_return_20d` 序列任务；5 日超额标签会在标签重建时生成，20 日超额标签复用现有 PIT 逻辑。
- 评估增加按决策日分组的 Rank IC、Top-K 平均超额收益、Top-Bottom spread，以及扣除股票双边成本假设后的指标。
- 5 日任务使用 5 日 purged/embargo horizon，20 日任务使用 20 日 purged/embargo horizon。
- 保留滚动时间外推、开发集 OOF、不可触碰的 252-session holdout 和 126-session stress slice。

## 服务器实验队列

### 阶段 A：数据和标签闸门

确认完整股票池为 162 只股票 + 5 只 ETF；检查每个标的的历史长度、PIT 样本数、特征缺失率、事件覆盖状态、财报可用时间和行业映射。若 `excess_return_5d` 尚未存在于冻结样本，先重建样本，不允许用未来数据补齐。

### 阶段 B：全池基线

在完整 167 标的上训练 `excess_return_5d`、`excess_return_20d`，先跑现有 PatchTST、TCN、iTransformer、Deep MLP，GPU 只使用 GPU0。主排序指标为 Rank IC、Top-K 超额收益和成本后 Top-K 收益，同时保留 MAE/Pinball 作为辅助指标。

### 阶段 C：信息集增量实验

按组加入并单独记录增量效果：

- 市场状态和宽基指数特征；
- 行业参考收益、行业强弱和行业编码；
- ETF 收益、成交和风格暴露；
- 宏观变量；
- PIT 财报和财务质量变化；
- PIT 事件、公告、新闻和事件缺失掩码。

每组都必须与同一冻结基线比较，禁止只报告加入全部特征后的最好结果。

### 阶段 D：面板模型

先实现 StockMixer 风格的特征混合、时间多尺度混合和股票池混合；再实现 MASTER 风格的市场引导特征选择、个股时间编码和股票间注意力。两类模型都必须以日期为 batch 的 panel 输入，不能把独立单股票模型改名后当作股票间注意力。

### 阶段 E：最终验证和组合回测

冻结最终测试集后只运行一次；报告全时期和分市场状态的 Rank IC、ICIR、Top-K 收益、换手、成本后收益、最大回撤、容量敏感性和 bootstrap 置信区间。只有在独立测试集和成本后组合表现均通过门槛时，才讨论 ensemble 或 deployment。

## 建议的验收门槛

门槛不是保证收益的承诺，而是防止把随机结果包装成模型能力的最低检查：

- Rank IC：跨滚动窗口大多数为正，均值和稳定性都要报告；不能只看一个 holdout 均值。
- Top-K：相对等权基线和行业/市场中性基线均有增益，并在扣除成本后仍为正。
- 稳定性：不同 seed、窗口、行业和市场状态不能由单一时期贡献全部收益。
- 统计可信度：记录候选试验数量，使用 purged/embargo；大量候选选择时增加 PBO/CSCV 或等价的多重检验控制。
- 数据可信度：最终报告必须带 dataset hash、feature hash、fold hash、模型 hash 和完整的失败/跳过原因。

## 可引用的论文依据

- Gu, Kelly, Xiu, *Empirical Asset Pricing via Machine Learning*：说明股票收益信号弱、非线性和特征交互重要，并强调严格的时间划分。见 [Review of Financial Studies](https://academic.oup.com/rfs/article/33/5/2223/5758276)。
- Li et al., *MASTER: Market-Guided Stock Transformer for Stock Price Forecasting*：提供市场引导特征选择、个股时间关系和股票间关系建模的思路。见 [AAAI-24 paper](https://ojs.aaai.org/index.php/AAAI/article/download/27767/27575)。
- Fan et al., *StockMixer: A Simple Yet Strong MLP-Based Architecture for Stock Price Forecasting*：提供适合有限金融数据的指标、时间尺度和股票池混合结构。见 [AAAI-24 paper](https://ojs.aaai.org/index.php/AAAI/article/download/28681/29322)。
- Bailey et al., *The Probability of Backtest Overfitting*：说明多次试验挑选最佳策略会系统性高估结果。见 [SSRN/NBER-style working paper record](https://escholarship.org/uc/item/4w1110bb)。
- *Re(Visiting) Time Series Foundation Models in Finance*：提醒通用时间序列基础模型在金融数据上可能失效，领域数据和预训练方式必须单独验证。见 [arXiv](https://arxiv.org/abs/2511.18578)。

## 对外介绍时的准确表述

可以说：系统完成了 PIT 数据重建、研究样本冻结、断点续跑和多模型基线，并正在把目标升级为 5 日/20 日超额收益和横截面排序。不要说“已经找到高精度模型”或“回测证明可稳定赚钱”；目前最有价值的结果是识别出方向分类接近随机，并据此把研究目标改成更符合投资决策的排序和成本后组合评价。
