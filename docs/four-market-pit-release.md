
# 历史/规划文档（当前不在交付范围）

> 本文描述四市场 PIT 的未来扩展，不是当前训练数据或发布状态。当前产品只以 CN A 股股票与 ETF 参考为主，且保持 `research_only`；请以 [`current-system.md`](current-system.md) 为准。

# Four-market PIT release contract

The production release unit is `market × decision_context × task`. China, the
United States, Hong Kong, and Japan share schemas, but never share approval.
`close_confirmed` and `pre_open` also use separate snapshots and artifacts.

The authoritative path is:

1. persist provider bytes with `AppendOnlyRawPayloadService`;
2. normalize immutable revisions and historical-universe state;
3. freeze a market snapshot and build feature/sample records;
4. run the machine-readable leakage audit;
5. publish schema-bearing Parquet partitions and their PostgreSQL catalog rows;
6. train with purged walk-forward folds while reserving 252 sessions as the
   final holdout and 126 sessions as its recent stress slice;
7. calibrate only time-out-of-fold scores;
8. approve one market/context/task manifest after all evidence and 20 shadow
   sessions exist.

Formal publication fails closed when provider authorization, `available_at`,
critical coverage, leakage evidence, artifact hashes, shadow evidence, or a
matching approved baseline is missing. Synthetic data is test-only. Minute
collection is disabled by default.

The checked-in provider entries remain `authorized: false`. This is deliberate:
the code and schemas are ready, but production data rebuild, model fitting, and
shadow observation require licensed external data and elapsed trading sessions.

## Execution matrix and evidence completeness

The release runner enumerates all **32** required scopes:

```text
CN / US / HK / JP
× close_confirmed / pre_open
× direction_1d / direction_5d / return_20d / drawdown_20d
```

Every scope is represented in the release index. A scope is never omitted or
marked as an ambiguous `pending` placeholder: it either has a verified dataset,
fold and task evaluation, or is explicitly `blocked` with its missing evidence.
For example, missing authorization, an exchange-calendar reference, PIT catalog
location, revision capability or historical `available_at` fields stops only
the affected market/context/task scope.

The checked-in formal configuration intentionally blocks all 32 scopes because
it contains no licensed provider credentials, calendar references, PIT catalog
or object-store evidence. That is the expected safe result for a public source
checkout; it is not a release approval. Before a scope can be approved, the
runner additionally requires a governed feature-ablation executor, a verified
cost/liquidity schedule, persisted deployable model artifacts with hashes, and
20 valid formal Shadow sessions.

Run a no-network orchestration check with:

```bash
python3 scripts/run_formal_pipeline.py --config config/formal_training.yaml --dry-run
```

Run the same command without `--dry-run` only after supplying the provider and
catalog configuration. A blocked exit code is deliberate and its generated
`provider_pit_gap_report.json` is the authoritative remediation list.
