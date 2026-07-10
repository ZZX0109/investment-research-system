# 阶段3/4/5 实现现状评审

> 基于 harness-loop-engineering-development-plan.md 与 backend/app.py 代码的实际对照
> 生成时间: 2026-07-03

## 阶段3：刷新与复盘 Loop

### 设计目标（文档定义）
- 过期证据扫描器：自动识别 `valid_until` 已过的 evidence
- 归档经验历史池：过期 evidence 不删除，归档到 `experience_history`
- 重新生成模型推断：证据刷新后触发模型重跑
- 报告版本对比：每次 run 记录 `risk_score`，与上一版对比

### 实现状态

| 设计项 | 实现状态 | 代码位置 |
|--------|----------|----------|
| 过期证据扫描 | ✅ 已实现 | `archive_expired_evidence()` (app.py:1138) |
| 归档经验历史池 | ✅ 已实现 | `experience_history` 表，每次刷新/启动时触发归档 |
| 证据刷新（行情/新闻/历史/公告） | ✅ 已实现 | `refresh_review_for_symbol()` (app.py:3054) |
| 刷新前后对比（risk_score_delta） | ✅ 已实现 | `evidence_refresh_items` 表含 `before_score`/`after_score`/`risk_score_delta` |
| claim 状态变化追踪 | ✅ 已实现 | `summarize_claim_status_change()` + `claim_status_map()` |
| 报告版本对比 API | ⚠️ 数据层已支持，无专用端点 | `report_versions` 在 `research_payload()` 中返回 |
| 模型重跑触发 | ⚠️ 刷新后未自动触发 `ml_infer` | `refresh_review_for_symbol` 不调用 `infer()` |

### 关键数据结构

```sql
-- 刷新 run 表
evidence_refresh_runs(refresh_id, user_id, refreshed_at, symbol_count, archived_count, summary)

-- 逐标刷新对比
evidence_refresh_items(
  refresh_id, symbol,
  before_score, after_score, risk_score_delta,
  before_claim_summary, after_claim_summary,
  evidence_changes JSON, conclusion_changes JSON, snapshot_status
)
```

### 已知缺口
1. 刷新后不自动触发模型重跑（`ml_infer` 需手动调用）
2. 无定时任务调度（需外部 cron 调 `POST /api/refresh/daily`）
3. 报告版本对比无专用 UI 端点（需前端自行对比 `report_versions` 字段）

---

## 阶段4：历史类比强化

### 设计目标（文档定义）
- `asOfDate` 截断校验：特征计算严格按 `asOfDate` 截断，防止未来函数
- 多维度特征匹配：估值分位 + 财报窗口 + 新闻情绪 + 市场状态 + 行业周期
- 风险分布输出：替代单点预测，输出回撤分位、波动率分位、VaR breach
- Point-in-Time Feature Store：每个特征字段记录 `asOfDate`/`source`/`availableAt`/`revisionId`

### 实现状态

| 设计项 | 实现状态 | 代码位置 |
|--------|----------|----------|
| `asOfDate` 截断（数据层） | ✅ 已实现 | `point_in_time_features` 表含 `as_of_date`/`available_at` |
| `asOfDate` 截断（特征构建） | ⚠️ `time_series_feature_builder` 工具定义中存在，实际特征构建代码需核查 | `ml/data/feature_store.py` |
| 多维度条件对齐 | ❌ Mock 实现 | `condition_alignment()` 返回写死数据 |
| Transformer embedding 相似度 | ⚠️ 表结构已建，写入逻辑需核查 | `scenario_embeddings` 表 + `ml/inference/retrieve_scenarios.py` |
| 历史类比当前实现 | ⚠️ 仍用规则匹配（价格涨幅触发） | `get_historical_analogies()` (app.py:2574) |
| 风险分布输出 | ✅ 已实现 | `ml/risk/distribution.py` 的 `build_risk_distribution()` |
| Point-in-Time Feature Store 审计 | ✅ 已实现 | `latest_feature_store_audit()` 在 `latest_ml_risk_summary()` 中调用 |
| 未来函数检查 | ✅ 已实现 | Judge 维度 `pit_feature_store` 检查 `futureLeakageCount` |

### 已知缺口
1. `get_historical_analogies()` 未使用 embedding，仍用规则匹配
2. `condition_alignment()` 是 mock，未接入真实多因子
3. `scenario_embeddings` 表的写入需确认 `retrieve_scenarios.py` 是否实际写入
4. 前端历史类比卡片是否展示 `condition_alignment` 字段需核查

---

## 阶段5：用户反馈与 Harness 改进

### 设计目标（文档定义）
- 用户反馈按钮：报告页增加"有用/有误/补充证据"反馈入口
- 失败 run 分类：Judge 低分 / 工具失败 / 证据过期 → 自动分类
- `harness_improvement_notes`：记录失败原因和改进建议
- 反馈 → Harness 改进闭环

### 实现状态

| 设计项 | 实现状态 | 说明 |
|--------|----------|------|
| 用户反馈表 | ❌ 未实现 | 无 `user_feedback` 表 |
| 用户反馈 API | ❌ 未实现 | 无对应端点 |
| 失败 run 自动分类 | ❌ 未实现 | `research_runs` 表无 `failure_category` 字段 |
| `harness_improvement_notes` | ❌ 未实现 | 无此字段 |
| 报告质量分记录 | ✅ 已实现 | `research_runs` 表含 `risk_score`，Judge 评分在 `evidence_audit` 中 |
| 工具调用失败记录 | ✅ 已实现 | `tool_invocations` 表含 `status`/`failure_reason` |

### 已知缺口
1. 整块功能未开始实现（文档中有设计，代码层无对应）
2. 需新增 `user_feedback` 表、`research_runs.failure_category` 字段
3. 失败 run 分类逻辑需基于 Judge 维度 + `tool_invocations.status` 实现

---

## 验收测试框架建议

### 阶段3 测试用例

| 测试场景 | 验证点 |
|----------|--------|
| 证据过期后刷新 | `archive_expired_evidence` 将过期 evidence 移入 `experience_history` |
| 刷新前后 risk_score 变化 | `evidence_refresh_items.risk_score_delta` 正确计算 |
| 刷新后 claim 状态变化 | `conclusion_changes` 正确记录 claim 状态变化 |
| 刷新不影响未过期 evidence | 未过期 evidence 的 `superseded_by` 为 NULL |

### 阶段4 测试用例

| 测试场景 | 验证点 |
|----------|--------|
| `asOfDate` 截断 | 特征计算中不使用 `asOfDate` 之后的数据 |
| 未来函数检查 | `futureLeakageCount > 0` 时 Judge 维度 `pit_feature_store` 不通过 |
| 风险分布输出 | `riskDistribution` 含 `drawdownQuantiles`/`volatilityQuantiles`/`varBreach` |
| 历史类比 `note` 字段 | 每个 analogy 的 `note` 含 "asOfDate 截断" 或 "样本外风险" |

### 阶段5 测试用例（待实现后补充）

| 测试场景 | 验证点 |
|----------|--------|
| 用户反馈提交 | `user_feedback` 表正确写入 |
| 失败 run 自动分类 | `research_runs.failure_category` 正确标注 |
| 反馈 → 改进闭环 | `harness_improvement_notes` 正确生成 |

---

## 优先级建议

1. **高优先级**：阶段4 的 `get_historical_analogies()` 接入 embedding（当前是规则匹配，与文档设计不符）
2. **高优先级**：阶段3 刷新后自动触发模型重跑（当前需手动调 `ml_infer`）
3. **中优先级**：阶段5 用户反馈功能实现（整块缺失）
4. **低优先级**：报告版本对比专用 UI 端点（数据层已支持）
