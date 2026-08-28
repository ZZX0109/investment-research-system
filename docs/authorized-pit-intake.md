# 授权 PIT 数据接入

`scripts/ingest_authorized_pit_source.py` 是授权数据供应商进入研究流水线的边界。它接收 JSON/JSONL、CSV 或 Parquet，要求每条记录包含：

- `dataset`、`symbol`、`observation_period`、`effective_at`
- `published_at`、`available_at`、`fetched_at`
- `revision_id`、`raw_payload_hash`、`normalized_record_hash`
- `quality_status`；当状态不是 `complete` 时还必须有 `missing_reason_code`

命令同时要求供应商授权声明（`authorized: true`），并明确声明历史 `available_at`、公告发布时间和修订链能力。接入器会检查：

- 所有时间字段的时区和先后关系：`published_at ≤ available_at ≤ fetched_at`
- SHA-256 原始及标准化记录哈希
- 同一 `dataset/symbol/observation_period` 的修订前后关系
- `supersedes_revision_id` 是否存在、是否形成单一有限链
- 缺失语义是否明确，避免把抓取失败当成“没有数据”

通过后，原始输入和规范化 JSONL 写入按 SHA-256 寻址的 landing 目录，并生成 manifest。接入结果为 `ready_for_pit`，但仍明确：

```text
active_snapshot_eligible = false
deployment_ready = false
```

它不会创建或修改 `var/cn-research/active.json`。后续仍必须经过标准层、PIT 快照、数据质量审计和泄漏审计，才能由人工/发布流程激活。

示例：

```bash
python3 scripts/ingest_authorized_pit_source.py \
  --input /secure/vendor/financial_2026.jsonl \
  --attestation /secure/vendor/attestation.json \
  --provider wind \
  --dataset cn_financial_authorized \
  --source-uri https://vendor.example/pit \
  --license-scope internal-research \
  --landing-root artifacts/authorized_pit_intake/landing \
  --output artifacts/authorized_pit_intake/latest.json
```

授权数据到达前，现有公开回补数据仍保持 `research_only`；禁止用抓取时间、文件修改时间或报告期末日期替代 `published_at`/`available_at`。
