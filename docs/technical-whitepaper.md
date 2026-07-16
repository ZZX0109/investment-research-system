# A 股量化研究平台技术白皮书

## 技术命题

本平台是面向金融投研的证据约束型研究系统。系统在 point-in-time 数据、模型不确定性与证据冲突条件下完成单资产未来 20 个交易日回撤风险研究，并在证据、特征、模型或引用不满足门禁时选择 repair、hold、block 或 abstain。它不执行交易，也不让语言模型计算收益率、回撤或风险概率。

## 权威执行图

内部类型化状态机是唯一执行器。流程依次经过 task intake、task classification、plan generation、tool selection、evidence collection、structured feature build、model inference、counter-evidence search、self audit、repair or abstain、report generation。每个节点持久化输入 hash、schema 版本、尝试次数、输出摘要、错误和审计事件。LangGraph 适配器只复用节点名称与边用于展示，不保存第二份状态。

语言模型只处理任务分类、受控计划、反方检索意图、引用审计和报告解释。OpenAI-compatible、Anthropic Messages、Ollama 与 Mock 通过同一 JSON Schema 接口接入。每次调用记录 provider、protocol、model、prompt/schema version、token、延迟、缓存与脱敏错误；返回不存在的 Evidence ID 时整次调用无效。单 run 最多 6 次 LLM、12 次工具调用、32,000 输入 token、4,000 输出 token、12 条证据、2 轮检索和 1 次修复。

## PIT 与证据图谱

事实链为 Source -> SourceDocument -> SourceRevision -> Evidence -> Citation -> Claim。相同 normalized hash 去重，新内容创建 revision，不覆盖旧事实。任何 `published_at > as_of` 的事实都不能进入历史 run。LLM 只能创建 proposed Claim，正式报告只读取 verified Claim 与确定性数字骨架。完成态 ResearchRun 固定输入快照、Evidence revision、FeatureContract、ModelRun、GateEvaluation 与 Report version。

## 模型门禁

正式模型任务是 `future_max_drawdown_20d`。运行时使用 `investment-risk-features-v1` 的 29 维特征；覆盖率低于 75% 直接 abstain。manifest 明确 primary RF 和 linear champion fallback。模型审批同时检查 AUROC、ECE、Brier、alert precision、drawdown lift、market、coverage group、regime、最近窗口、PIT 与数据覆盖，研究报告不能反向修改 promotion 状态。

## 失败与降级

Provider 失败只切换到配置的 fallback，不重启 run。无 LLM 时生成确定性报告；模型 primary 失败时切换 champion；两者都失败时输出 `risk_unavailable`；引用缺失、权威冲突、未来信息或特征不足时 abstain。缓存必须保留真实抓取时间，synthetic 数据不能冒充 real。

## 安全边界

工具只能来自 allowlist，LLM 不能生成 SQL、URL、代码、买卖指令或修改事实。凭据由加密 vault 解析，不进入 prompt、日志或缓存。所有核心资源带 owner，Viewer 只能读取授权的固定 run。对象存储保存原始 PDF、页面和表格，关系库保存 hash、定位和权限。

## 可复现交付

训练采用 real + full + walk-forward。每轮保存数据版本、特征合同、模型卡、校准、fold 指标、审批报告和回滚 manifest。研究产物由 `scripts/generate_model_research_report.py` 从权威 JSON 生成；多模态实验由 `scripts/run_multimodal_experiment.py` 对固定 SHA256 的腾讯 2024 年报执行。
