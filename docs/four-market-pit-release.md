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
