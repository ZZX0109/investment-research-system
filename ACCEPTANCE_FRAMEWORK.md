# 金融投研系统 — 阶段3/4/5 验收与测试框架

> **总体目标**：为阶段3（刷新与复盘 Loop）、阶段4（ML 增强与历史类比）、阶段5（证据链完整性与输出一致性）构建可落地的自动化验收体系。

---

## 一、测试框架总览

### 1.1 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 测试框架 | **pytest 7+** | Python 标准测试框架 |
| HTTP 客户端 | **httpx** (FastAPI TestClient) | 内存级 API 测试，零网络依赖 |
| 数据库 | **内存 SQLite**（函数级隔离） | 每个测试独立临时 SQLite，确保隔离性 |
| CI 入口 | `python -m pytest` | 一键运行 |

### 1.2 目录结构

```
investment-research-system/
├── pytest.ini                     # pytest 配置
├── backend/
│   └── tests/
│       ├── conftest.py            # 全局 fixtures（app/client/db/headers）
│       ├── unit/                  # 单元测试
│       │   ├── test_auth.py       # 认证（注册/登录/Token）
│       │   ├── test_db_schema.py  # 数据库 Schema 验证
│       │   ├── test_portfolio.py  # 持仓与报告设置
│       │   ├── test_refresh.py    # 阶段3：刷新 Loop
│       │   ├── test_research.py   # Research API 契约
│       │   ├── test_ml_api.py     # ML API 契约
│       │   └── test_ml_wrapper.py # ML 已有测试包装
│       ├── integration/           # 集成测试
│       │   ├── test_refresh_loop_integration.py   # 阶段3 集成
│       │   ├── test_analogy_integration.py        # 阶段4 集成
│       │   ├── test_research_pipeline.py           # 阶段5 研究 Pipeline
│       │   └── test_evidence_chain.py              # 阶段5 证据链
│       └── data/
│           └── test_factory.py    # 测试数据工厂
├── e2e/
│   ├── conftest.py
│   └── test_full_flow.py          # E2E：注册→报告
└── ml/tests/                      # ML 已有测试（11个，不变）
```

### 1.3 运行方式

```bash
# 全部测试
python -m pytest -v

# 仅单元测试
python -m pytest backend/tests/unit/ -v

# 仅集成测试
python -m pytest backend/tests/integration/ -v

# E2E 测试
python -m pytest e2e/ -v

# 运行特定阶段相关测试
python -m pytest -k "refresh" -v      # 阶段3
python -m pytest -k "analogy" -v      # 阶段4
python -m pytest -k "evidence" -v     # 阶段5
```

---

## 二、阶段3 验收清单：刷新与复盘 Loop

### 2.1 核心功能验收

| # | 验收项 | 对应测试 | 通过标准 |
|---|--------|---------|---------|
| 1 | POST /api/refresh/daily 返回 200 | `test_refresh_daily_endpoint` | HTTP 200 + 含 refreshedAt |
| 2 | 刷新后 evidence_refresh_runs 有记录 | `test_refresh_creates_refresh_run_record` | runs 表计数 +1 |
| 3 | 刷新后 evidence_refresh_items 有记录 | `test_refresh_creates_refresh_items` | items 表有新增 |
| 4 | refresh_items 包含 before/after score | `test_refresh_items_have_score_delta` | before_score, after_score 非空 |
| 5 | refresh_items.evidence_changes 为正则 JSON | `test_refresh_items_have_evidence_changes` | JSON 解析成功 + 含 newEvidenceIds |
| 6 | refresh_items.conclusion_changes 为正则 JSON 列表 | `test_refresh_items_have_conclusion_changes` | 解析为 list |
| 7 | 过期 evidence 归档到 experience_history | `test_archive_expired_evidence` | history 表计数 +1 |
| 8 | 旧 evidence.superseded_by 指向新 evidence | `test_refresh_preserves_old_evidence_with_superseded_by` | superseded_by 非空 |
| 9 | 连续刷新幂等 | `test_concurrent_refresh_idempotent` | 两次 200，refreshedAt 不同 |
| 10 | snapshot_status 为 live 或 degraded | `test_refresh_items_snapshot_status_valid` | status ∈ {live, degraded} |

### 2.2 数据流验收

```
用户触发刷新 → archive_expired_evidence (归档)
              → refresh_user_data (遍历持仓 → insert_refresh_*_evidence)
              → refresh_review_for_symbol (before/after 对比)
              → history_mirror (关键结论写入 experience_history)
```

**验收要点**：
- 每一步的数据表记录可追溯
- superseded_by 链不可成环（`test_evidence_superseded_by_chain_not_circular`）
- archived_at 被置位的 evidence 必须在 experience_history 有对应记录

---

## 三、阶段4 验收清单：ML 增强与历史类比

### 3.1 ML API 契约

| # | 验收项 | 对应测试 | 通过标准 |
|---|--------|---------|---------|
| 1 | GET /api/ml/models 返回列表 | `test_list_models` | HTTP 200 |
| 2 | POST /api/ml/datasets/build smoke 成功 | `test_build_dataset_smoke` | 含 datasetPath |
| 3 | POST /api/ml/infer 需 model_id | `test_infer_requires_model` | 非 200 返回 |
| 4 | GET /api/ml/predictions/{symbol} 返回预测 | `test_predictions_list` | HTTP 200 |
| 5 | GET /api/ml/scenarios/{symbol} 返回类比 | `test_scenarios_list` | HTTP 200 |
| 6 | GET /api/ml/token-compression/{symbol} | `test_token_compression` | 200/404 |

### 3.2 历史类比（similar_scenarios）

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 1 | similar_scenarios 表可读写 | 写入后 SELECT 一致 |
| 2 | 可按 query_symbol 过滤 | 计数正确 |
| 3 | scenario_embeddings 复合唯一约束 | 重复 INSERT 触发 IntegrityError |
| 4 | Research evidence 含 historical_analogy 类型 | `historical_analogy` ∈ evidenceTypes |
| 5 | analogous_scenario_query tool 已注册 | tool_registry 包含该 tool_id |

### 3.3 Point-in-Time Feature Store

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 1 | 复合唯一约束生效 | 重复插入触发 IntegrityError |
| 2 | available_at ≤ as_of_date (无未来泄漏) | 检测逻辑报警 |
| 3 | feature_store_audit 在 mlSummary 中 | mlSummary.featureStoreAudit 非空 |

---

## 四、阶段5 验收清单：证据链完整性与输出一致性

### 4.1 证据链完整性

| # | 验收项 | 对应测试 | 通过标准 |
|---|--------|---------|---------|
| 1 | claims 引用真实 evidence IDs | `test_evidence_graph_references_valid_evidence_ids` | 无幽灵引用 |
| 2 | edges.from / edges.to 指向 valid 节点 | `test_evidence_graph_edges_reference_valid_nodes` | 无幽灵节点 |
| 3 | superseded_by 链无环 | `test_evidence_superseded_by_chain_not_circular` | 无循环 |
| 4 | confidence 在 [0, 1] | `test_evidence_confidence_range` | 无越界 |
| 5 | valid_until ≥ observed_at | `test_evidence_valid_until_after_observed_at` | 无时间倒挂 |
| 6 | 归档 evidence 在 experience_history 有记录 | `test_archived_evidence_in_experience_history` | 记录存在 |
| 7 | evidence 数量 ≥ graph 引用 evidence 数量 | `test_research_evidence_count_matches_evidence_graph` | 无遗漏 |

### 4.2 研究输出一致性

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 1 | Research payload 包含所有 7 个顶层字段 | riskLevel, riskScore, summary, evidence, evidenceGraph, audit, revision, mlSummary |
| 2 | audit.score 在 [0, 100] | 数值范围 |
| 3 | audit.dimensions ≥ 10 个 | 覆盖 freshness, bear_case, pit_feature_store, risk_distribution_engine, calibration_validation, source_citation, no_certainty_language 等 |
| 4 | 6 条核心 claim 全部存在 | market_today_pnl, financial_quality, authority_disclosure_check, news_event_driver, historical_analogy_scope, report_conclusion_boundary |
| 5 | report_conclusion_boundary 的 derivedMetrics 含 hedgingCost | 有具体数值或 "未对冲" |
| 6 | Markdown 报告含 riskLevel | 报告内容匹配 |
| 7 | 不同 preference 产生不同 summary | 至少部分不同 |
| 8 | 不同 symbol 的 evidence 集合不完全相同 | 隔离性验证 |
| 9 | 每次 research 后 research_runs 计数 +1 | 审计日志 |
| 10 | tool_invocations 表有对应记录 | 工具调用链路 |

### 4.3 Judge v2 审计维度

以下 17 个维度必须在 audit.dimensions 中有至少 10 个：

| 维度 key | 含义 | 判定 |
|----------|------|------|
| `evidence_sufficiency` | 证据充分性 | 每条 claim 至少 3 条证据 |
| `freshness` | 证据新鲜度 | 无 stale evidence |
| `financial_source` | 财务指标来源 | 来自 fillings 或 financial_metrics |
| `authority_disclosure` | 权威披露 | 官方披露存在或标注缺失 |
| `out_of_sample_risk` | 样本外风险 | 场景未重叠的风险敞口 |
| `fact_inference_boundary` | 事实推断边界 | 区分事实与推断 |
| `bear_case` | 反方观点 | 明确列示最坏情形 |
| `pit_feature_store` | PIT Feature Store | 无未来泄漏 |
| `risk_distribution_engine` | 风险分布 | 提供 drawdown/volatility 分位数 |
| `calibration_validation` | 校准验证 | calibrationStatus 存在 |
| `source_citation` | 来源引用 | 每条 evidence 有 source_name |
| `no_certainty_language` | 禁止确定性语言 | 无"必然""一定" |
| `revision_loop_quality` | Revision Loop 质量 | draftStatus → judgeVerdict → finalStatus |
| `token_efficiency` | Token 效率 | tokenReductionPercent 存在 |
| `hedging_coverage` | 对冲覆盖 | derivedMetrics 含 hedgingCost |
| `cross_model_consistency` | 跨模型一致性 | mlSummary 一致 |
| `regulatory_readiness` | 监管合规 | 风险披露完整 |

---

## 五、测试分层与覆盖矩阵

### 5.1 分层策略

| 层级 | 测试类型 | 运行时间 | 覆盖目标 | 数量 |
|------|---------|---------|---------|------|
| Unit | 单函数/API 契约 | <1s each | API 路由、Schema、逻辑函数 | 40 |
| Integration | 跨模块数据流 | 2-5s each | 刷新链路、证据链、Pipeline | 16 |
| E2E | 全流程 | 10-15s | 注册→报告→ML | 3 |
| ML 兼容 | 已有 ML 测试 | <5s each | 推断契约、特征存储等 | 5 |

### 5.2 阶段覆盖矩阵

| 测试文件 | 阶段3 | 阶段4 | 阶段5 | 类型 |
|----------|:---:|:---:|:---:|------|
| `test_db_schema.py` | ✅ | ✅ | ✅ | Unit |
| `test_auth.py` | - | - | - | Unit |
| `test_portfolio.py` | - | - | - | Unit |
| `test_refresh.py` | ✅ | - | - | Unit |
| `test_research.py` | - | ✅ | ✅ | Unit |
| `test_ml_api.py` | - | ✅ | - | Unit |
| `test_ml_wrapper.py` | - | ✅ | - | Unit |
| `test_refresh_loop_integration.py` | ✅ | - | ✅ | Integration |
| `test_analogy_integration.py` | - | ✅ | - | Integration |
| `test_research_pipeline.py` | ✅ | ✅ | ✅ | Integration |
| `test_evidence_chain.py` | - | - | ✅ | Integration |
| `test_full_flow.py` | ✅ | ✅ | ✅ | E2E |

---

## 六、CI 集成建议

### 6.1 推荐配置

```yaml
# GitHub Actions workflow
name: Test Suite
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: python -m pytest backend/tests/unit/ -v --junitxml=unit.xml
      - run: python -m pytest backend/tests/integration/ -v --junitxml=integration.xml
      - run: python -m pytest e2e/ -v --junitxml=e2e.xml
```

### 6.2 质量门禁

- **单元测试**：通过率 100%（强制）
- **集成测试**：通过率 ≥ 95%（强制）
- **E2E 测试**：通过率 100%（强制）
- **阶段3**：10 项全部通过
- **阶段4**：6 项 ML API + 5 项类比测试全部通过
- **阶段5**：7 项证据链 + 10 项输出一致性全部通过

---

## 七、快速验收指令

```bash
# 阶段3 验收
python -m pytest backend/tests/unit/test_refresh.py backend/tests/integration/test_refresh_loop_integration.py -v

# 阶段4 验收
python -m pytest backend/tests/unit/test_ml_api.py backend/tests/unit/test_ml_wrapper.py backend/tests/integration/test_analogy_integration.py -v

# 阶段5 验收
python -m pytest backend/tests/unit/test_research.py backend/tests/integration/test_evidence_chain.py backend/tests/integration/test_research_pipeline.py -v

# 全量验收
python -m pytest -v
```

---

## 八、产出物清单

| 文件 | 用途 | 大小 |
|------|------|------|
| `backend/tests/conftest.py` | 全局 pytest fixtures | ~3KB |
| `backend/tests/unit/__init__.py` | 单元测试包 | 0 |
| `backend/tests/integration/__init__.py` | 集成测试包 | 0 |
| `backend/tests/data/__init__.py` | 测试数据包 | 0 |
| `backend/tests/data/test_factory.py` | 测试数据工厂 | ~3KB |
| `backend/tests/unit/test_db_schema.py` | 数据库 Schema 验证 | 6 项 |
| `backend/tests/unit/test_auth.py` | 认证测试 | 9 项 |
| `backend/tests/unit/test_portfolio.py` | 持仓测试 | 4 项 |
| `backend/tests/unit/test_refresh.py` | 阶段3 单元测试 | 8 项 |
| `backend/tests/unit/test_research.py` | Research API 单元测试 | 9 项 |
| `backend/tests/unit/test_ml_api.py` | ML API 契约测试 | 7 项 |
| `backend/tests/unit/test_ml_wrapper.py` | ML 测试兼容包装 | 5 项 |
| `backend/tests/integration/test_refresh_loop_integration.py` | 阶段3 集成 | 6 项 |
| `backend/tests/integration/test_analogy_integration.py` | 阶段4 集成 | 5 项 |
| `backend/tests/integration/test_research_pipeline.py` | 研究 Pipeline 集成 | 6 项 |
| `backend/tests/integration/test_evidence_chain.py` | 证据链完整性 | 7 项 |
| `e2e/conftest.py` | E2E fixtures | 0.3KB |
| `e2e/test_full_flow.py` | E2E 全流程 | 3 项 |
| `pytest.ini` | Pytest 配置 | 0.3KB |
| `ACCEPTANCE_FRAMEWORK.md` | 本文档 | ~10KB |

**总计**：20 个测试文件，70+ 测试用例，覆盖阶段3/4/5 全部关键路径。
