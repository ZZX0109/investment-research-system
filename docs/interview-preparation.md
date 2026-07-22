# 面试准备：大模型评测、Benchmark 与可信AI

更新时间：2026-07-16

本文用于准备与“大模型评测、医疗健康大模型 Benchmark、LLM-as-a-Judge、Reward Model 和用户体验评测”相关的实习面试。内容结合本人当前的两个项目：AI 测试官项目和投研系统项目。

## 一、招聘内容留档

### 项目方向

正在建设一个面向开源社区的技术 Benchmark，关注大模型在 C 端医疗健康问答场景中的风格、用户体验与安全边界。项目目标不是简单评价医学知识题，而是研究模型在真实用户场景下能否做到清楚、直接、可执行，不过度自信、不迎合错误诉求、语气得体，并且在医疗安全约束下保持良好的用户体验。

该方向结合 LLM Evaluation、LLM-as-a-Judge、Reward Model、用户反馈建模、医疗沟通评测和 Benchmark 设计，预期产出包括公开数据集、评测协议、Baseline 结果、技术报告与论文。

### 工作内容

- 调研大模型评测、医疗大模型 Benchmark、用户体验评测、LLM-as-a-Judge、Reward Model、sycophancy 与 anti-sycophancy 等方向的最新论文。
- 参与设计医疗健康 C 端风格评测的 taxonomy、rubric、annotation protocol 和数据构建流程。
- 基于真实或模拟用户 query 构建测试集，设计多维度标签，包括可执行性、不确定性校准、反迎合、语气适配和医疗安全 hard gate 等。
- 使用 GPT、Claude、Gemini 和国内大模型 API 运行模型回答与自动评测实验，分析不同 Judge 的稳定性、一致性和偏差。
- 参与 human annotation、LLM-as-a-Judge 和 Reward Model 闭环评测方案设计，并进行验证实验。
- 参与 Reward Model、Judge Model 的训练与评估，包括偏好数据构建、训练目标设计、开源模型微调、校准分析和误差分析。
- 梳理实验结果，产出可复现分析报告、Benchmark Card、论文相关工作和方法部分初稿。
- 通过线上数据，将业务场景问题抽象为公开、可复现、可研究的技术 Benchmark 问题。

### 基本要求

- 对大模型评测、对齐、RLHF/RLAIF、LLM-as-a-Judge、Reward Model 或 Benchmark 构建有浓厚兴趣。
- 具有较强论文阅读和总结能力，能够快速提炼方法、数据、指标、局限性和可借鉴点。
- 熟悉 Python，能够完成数据处理、API 调用、实验脚本、结果统计和可视化。
- 有实际模型训练或微调经验，熟悉 PyTorch 和 Hugging Face Transformers，能够独立完成数据加载、训练、评估、checkpoint 管理和实验复现。
- 理解 SFT、分类/回归 Reward Model、pairwise preference learning 等基本训练范式，理解 pointwise、pairwise 和 ordinal preference 等监督目标的区别。
- 熟悉 LoRA、QLoRA、PEFT、tokenization、chat template、loss masking、学习率和 batch size 等微调关键环节，能够定位过拟合、类别不平衡、训练/测试泄漏和训练不稳定问题。
- 具备严谨的实验意识，理解 train/test split、标注一致性、bootstrap、置信区间、ablation 和 bias check 等概念。
- 表达清晰，能够撰写高质量中英文技术文档。
- 能够稳定投入每周 3–5 天，实习期不少于 3 个月，6 个月及以上优先。

### 加分项

- 有 LLM Evaluation、NLP Benchmark、RLHF、Reward Model、preference data 或 LLM-as-a-Judge 相关研究或项目经验。
- 有 Reward Model、Generative Reward Model、DPO、RLHF、RLAIF 或 preference optimization 训练经验。
- 使用过 TRL、OpenRLHF、LLaMA-Factory、verl、DeepSpeed、FSDP 等训练框架，或有多卡训练、混合精度、显存优化和断点恢复经验。
- 有数据集构建、人工标注协议设计、众包质量控制和人类偏好实验经验。
- 有论文投稿、开源 Benchmark、leaderboard、Hugging Face dataset 或 GitHub repo 维护经验。

招聘内容来源：用户提供的三张岗位截图，原始文件名为 `36972003da731fa26db6b96928b634d7.png`、`08029f1d978b75154b93bba8717d8fd5.png` 和 `4885ca9b4612ba8fee56517c02b8bcc9.png`。

## 二、两个项目与岗位的匹配关系

### AI 测试官项目：主匹配项目

AI 测试官与岗位的核心方向高度匹配，重点对应 LLM Evaluation、LLM-as-a-Judge、Benchmark、证据驱动评测、安全 hard gate、人工复核和用户体验评价。

项目当前已经实现需求和代码变更分析、测试计划生成、权限审批、浏览器执行、截图/DOM/Network/Console/Trace 证据采集、Artifact v2、证据哈希、失败归因、规则 Judge、LLM Planner、LLM Judge、人工复核、Benchmark 和生产运行链路。

最适合的面试定位是：

> 我构建了一个证据驱动的 AI 测试与评测工作台，把需求和代码变更转化为可执行测试计划，通过浏览器运行获得结构化证据，再用确定性门禁、LLM Judge 和人工决策生成可审计的质量结论。

当前项目最能对应招聘要求的技术点包括：

- Benchmark：多案例、多执行通道、开发集/盲测集、重复运行、模型对照和验收阈值。
- LLM-as-a-Judge：LLM Planner、LLM Judge、规则 Judge、证据引用校验、Judge 冲突处理和降级机制。
- 人工反馈：人工标签、人工复核、发布建议和人机协同决策。
- 安全评测：提示注入、伪造证据、无证据结论、越权执行和 Artifact 完整性。
- 用户体验评测：需求覆盖、可执行性、任务成功率、证据充分性和最终发布建议。
- 实验工程：LLM 调用记录、模型版本、Prompt 版本、Token、耗时、运行状态和可复现报告。

当前开发集实验已经出现真实 LLM 增益，但仍需谨慎表达。最新实验完成了90次开发集运行，完整 LLM 的 Macro F1 约为0.822，最终决策准确率约为0.833，误放行率为0；但误阻塞率约为0.5，人工复核率约为0.333，当前状态仍是开发集结果，盲测尚未完成。因此面试时应说“已经完成开发集验证并观察到增益，正在进行盲测和误阻塞优化”，不要说“已经完成通用 Benchmark”。

### 投研系统项目：高风险场景与模型可靠性案例

投研系统与医疗大模型评测不是同一个垂直领域，但可以作为高风险 AI 场景和可信模型研究案例。它对应的岗位能力主要是数据治理、模型评估、不确定性校准、风险门禁、时间切分、数据泄漏防护和持续前向验证。

投研系统当前采用零预算 A 股研究模式，使用公开研究数据，明确区分 research-only 和正式授权模式。系统包含 Research PIT、固定股票池、数据快照、泄漏报告、Walk-forward、purge/embargo、模型校准、abstain、模型 roster 和 Research Shadow。

最适合的面试表达是：

> 投研系统让我处理了高风险预测中的数据可用时间、样本泄漏、模型校准和主动拒绝问题。虽然它不是医疗问答项目，但其中的“证据不足时不输出结论、模型和数据版本可追溯、预测结果持续前向验证”等思想可以迁移到医疗大模型安全评测。

投研系统不要被包装成“实时荐股系统”，而应定位为公开数据条件下的研究级模型验证平台。正式生产模式因缺少商业数据授权而保持阻断，这是正确的数据合规设计。

## 三、面试必须系统掌握的知识路线

### 第一阶段：LLM Evaluation 基础

需要理解如何把开放式用户问题转成可测试的 Benchmark。具体包括测试集 taxonomy、场景覆盖、正负样本、边界案例、gold label、rubric、评测协议和 Benchmark Card。要能解释一个好评测集不仅测试知识正确性，还需要覆盖用户意图、回答风格、可执行性、不确定性、拒答、安全性和错误归因。

需要掌握的指标包括 Accuracy、Precision、Recall、F1、Macro F1、AUROC、PR-AUC、Exact Match、NDCG、Pairwise Win Rate、拒答率、人工复核率、一致性、误放行率和误阻塞率。还要理解 bootstrap 置信区间、样本量影响、数据泄漏、测试集污染、分层采样和跨模型比较。

### 第二阶段：人工标注与偏好数据

需要理解 pointwise、pairwise 和 ordinal 标注。Pointwise 是对单个回答按照 rubric 独立评分，pairwise 是比较两个回答谁更好，ordinal 是对多个回答排序。要学习如何写标注指南、处理边界案例、设置质检样本、衡量标注者一致性，并使用 Cohen’s Kappa、Krippendorff’s Alpha 或 bootstrap 分析标注可靠性。

医疗健康场景还需要把安全标签拆开，例如事实错误、过度自信、危险建议、缺少就医升级、错误安慰、迎合用户错误判断、拒答过度、语气不合适和缺少可执行下一步。

### 第三阶段：LLM-as-a-Judge

需要掌握 reference-based Judge、reference-free Judge、单模型 Judge、多模型 Judge和人类校准。重点理解 Judge 的位置偏差、长度偏差、模型偏好、风格偏好、过度自信、过度保守、sycophancy 和证据幻觉。

需要能够设计 Judge 实验：让人类标签作为参照，比较规则 Judge 和 LLM Judge 的一致性，检查Judge是否引用真实证据，分析不同模型在不同类别和不同风险等级上的误差，并使用人工样本校准阈值。

### 第四阶段：安全评测与人机协同

需要把机器硬门禁与模型软判断分离。机器硬门禁负责证据存在、哈希正确、核心步骤执行、权限合法和安全红线；LLM负责解释、归因、排序和推荐；人工负责争议裁决和最终升级。模型不能覆盖硬门禁，不能把失败升级为通过。

需要熟悉提示注入、工具越权、伪造证据、恶意网页文本、数据泄漏、隐私暴露、错误医疗建议和错误拒答等测试方式。

### 第五阶段：Reward Model 与偏好优化

当前不需要马上训练大规模 Reward Model，但需要系统理解其基本流程：构造偏好数据，训练 pointwise/pairwise/ordinal Reward Model，进行校准和误差分析，再用于候选回答排序或策略优化。

之后再学习 SFT、LoRA、QLoRA、PEFT、DPO、IPO、RLHF、RLAIF、TRL、DeepSpeed、FSDP、混合精度、checkpoint 和断点恢复。学习顺序应是先评测和数据，再 Reward Model，最后偏好优化；否则容易只会训练而不会证明模型变好了。

## 四、面试时如何讲两个项目的关系

两个项目可以组成一个统一技术故事：AI 测试官是通用的可信 AI 评测基础设施，投研系统是一个具有真实数据风险和模型风险的复杂被测应用。AI 测试官可以测试投研系统的数据刷新、模型训练、预测状态、权限、报告、证据链和 abstain 行为；投研系统则为 AI 测试官提供长任务、多状态、模型输出和高风险决策场景。

可以这样总结：

> 我的项目不是只让模型输出答案，而是建立了从输入、执行、证据、评测到人工决策的闭环。AI 测试官解决的是如何判断 AI 系统是否可靠，投研系统解决的是如何在数据不完备和预测不确定时安全地使用模型。两个项目共同关注可复现、可审计、可拒答和风险可控。

## 五、可能被追问的问题

### 为什么需要 LLM-as-a-Judge？

规则适合判断结构化断言，例如元素是否存在、接口是否返回正确、证据是否完整；LLM Judge适合判断开放式需求覆盖、失败归因、回答质量和复杂语义。但LLM Judge本身会有偏差，因此不能单独作为最终安全门禁，需要人类标签、规则门禁和Judge校准。

### 如何证明 Judge 变好了？

使用固定开发集、冻结盲测集和多次重复实验，使用人类标签作为参照，比较Macro F1、决策准确率、误放行率、误阻塞率、人工复核率、证据引用准确率和一致性，并报告置信区间和失败案例，而不是只展示平均分。

### 如何避免模型被输入内容攻击？

把需求、diff、DOM、日志、网页文本和证据payload全部当作不可信数据，将评测规则和机器采集事实作为可信输入；对工具和权限设硬边界；对证据ID进行白名单校验；LLM结论不能覆盖机器门禁；遇到证据不足或冲突时必须进入人工复核。

### 为什么投研系统没有付费数据仍然有价值？

它定位为零预算研究平台，重点研究数据快照、可用时间、泄漏防护、模型校准、abstain和Shadow前向验证，不宣称实时交易或商业级行情服务。公开数据足以支撑研究方法、Benchmark和可复现实验，但正式生产需要额外数据授权。

### 为什么不直接训练一个更大的模型？

项目目标是评测和验证模型在真实任务中的可靠性，而不是单纯追求参数规模。先建立高质量数据、评测协议、Judge校准和安全门禁，才能判断更大的模型是否真的改善了用户体验和安全性。

## 六、当前需要补强的证据

AI 测试官需要修复项目映射合同测试，完成 `npm test` 全绿；完成冻结盲测；降低误阻塞率和人工复核率；完成生产 Compose 验收；重新运行最新版本的完整 Demo。

投研系统需要运行 [run_cn_research_demo.py](/Users/afa/Desktop/Hack/scripts/run_cn_research_demo.py)，生成四类任务的研究模型产物、研究 roster、评估报告和第一批 Research Shadow 记录。当前仍应保持 `deployment_ready: false`，不把免费研究数据包装成正式交易模型。

## 七、面试准备优先级

最优先学习 LLM Evaluation、Benchmark 设计、LLM-as-a-Judge、人工标注协议、统计显著性和安全评测；第二优先学习 Reward Model、偏好数据、DPO 和 RLAIF；第三优先学习 Hugging Face、TRL、LoRA/QLoRA、checkpoint 管理和本地模型训练；投研系统相关内容重点准备 PIT、Walk-forward、校准、abstain、Shadow 和数据血缘。

最重要的面试原则是：不把“代码已实现”说成“模型效果已证明”，不把“开发集结果”说成“盲测结果”，不把“research-only”说成“生产可用”，并且能够明确解释系统在什么情况下会拒绝输出结论。
