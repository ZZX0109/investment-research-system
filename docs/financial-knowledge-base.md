# A 股金融投研知识库

## 1. 它解决什么问题

量化模型负责计算 1/5 日方向概率、20 日收益区间和 20 日回撤风险；金融知识库负责回答“依据是什么、规则是什么、公告说了什么、资料是否完整”。知识库不会生成新的数值预测，也不会给出买卖指令。

知识库包含四类内容：全 A 股公告元数据；按需下载的公司公告正文；证监会、沪深北交易所、央行、统计局和财政部公开资料；当前账号上传的 PDF、DOCX、TXT、Markdown 私有资料。

## 2. 时间与修订

文档的可见时间固定为：

```text
available_at = max(来源发布时间, 平台首次成功获取时间)
```

更正、补充和撤回不会覆盖旧内容。新正文产生新的 revision，旧 revision 的有效期截止到新版本可见时间。任何带 `as_of` 的检索只读取当时已经可见且有效的版本。历史回补无法证明真实首次可见时间时，记录 `historical_available_at_unproven_public_backfill`。

## 3. 检索流程

1. 按市场、证券代码、文档类型、账号权限、`as_of` 和 revision 过滤。
2. 使用本地词组/全文检索召回公司名称、证券代码、规则条款和精确术语。
3. 若本地 BGE 模型已安装，则增加中文语义召回。
4. 融合关键词、语义、权威度和标的匹配分数。
5. 去重并限制单一来源占比。
6. 保存 `KnowledgeRetrievalSnapshot`，记录实际使用的 chunk 和 citation ID。

向量模型不可用时只降级为关键词检索，页面会显示“关键词”，不会调用付费 API。

## 4. 安装与运行

```bash
python3 -m pip install -e ".[knowledge,documents]"
python3 scripts/sync_financial_knowledge.py --mode incremental
python3 scripts/reindex_financial_knowledge.py
python3 scripts/audit_financial_knowledge.py
python3 scripts/evaluate_financial_knowledge.py
```

同步脚本的退出码非零表示免费来源、覆盖率或评测门槛未满足。它不会读取合成数据或伪造“没有公告”。

## 5. 用户资料安全

上传文件绑定 `owner_user_id`，公共搜索只读取公开资料，登录用户只能额外读取自己的私有资料。检索文本是“不可信数据”，LLM 不得执行文档内的提示词。删除操作同时删除原始对象、文档记录、切片和向量。

## 6. Agent 工具边界

研究助手只能调用只读知识工具：搜索、读取文档、公告查询、规则修订、覆盖检查和公司披露对比。工具返回原文片段、来源 URL、发布时间、页码或条款、revision、PIT 状态和 citation ID。最终引用卡由后端从工具结果生成，模型不能自行编造引用。

数字预测只能来自量化研究工具。检索不到公司资料时，助手仍可解释现有量化结果，但必须清楚说明缺少公司级证据。

## 7. 验收

- `python3 -m pytest -q`
- `python3 -m pytest -q tests/test_alembic_migrations.py`
- `npm test -- --run`
- `npm run build:workbench`
- `python3 scripts/audit_financial_knowledge.py`
- `python3 scripts/evaluate_financial_knowledge.py`

所有知识产物保持 `data_tier=research_pit`、`deployment_ready=false`。知识库完善不会把免费数据或量化模型提升为正式交易系统。
