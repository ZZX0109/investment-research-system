# 算法训练 Runbook

更新时间: 2026-07-03

目标顺序: 先完成最小 demo 算法，再推进可靠的一定规模算法。

## 1. 最小 demo 算法

用途: 快速证明 Investment Research 能从行情结构化数据生成风险分布、历史相似情景、校准指标和 Judge v2 审计结果。

默认标的:

- `NVDA`
- `TSLA`
- `QQQ`
- `XLE`
- `510300`
- `600519`

运行命令:

```bash
npm run train:minimal
```

等价 Python 命令:

```bash
python3 -m ml.pipelines.minimal_demo --allow-synthetic
```

产物:

- `artifacts/datasets/minimal_demo_v1/dataset.json`
- `artifacts/models/risk_tabular_min_v1/model.pkl`
- `artifacts/models/risk_tabular_min_v1/metrics.json`
- `artifacts/models/risk_tabular_min_v1/model_card.json`
- `artifacts/pipelines/minimal_demo_v1/manifest.json`

最小 demo 验收门槛:

- 至少 4 个标的。
- 至少 24 条训练样本。
- Point-in-Time future leakage 为 0。
- 输出 ECE、pinball loss、CRPS、VaR breach rate。
- walk-forward 至少 1 个窗口。
- purged CV 至少 1 个 fold。
- 预览标的能完成推理和相似情景检索。

注意: `--allow-synthetic` 只用于演示和工程验证，页面和 model card 会标注 `sourceStatus=degraded`。

## 2. 最小可用算法真实数据版

用途: 去掉 synthetic 行情，先用 20-50 个真实高流动性标的训练 `risk_tabular_real_v1`。这一层是后续 CNN/Transformer 和 300-600 标的扩展的质量基线。

默认标的:

- 第一批 30 个美股大盘股和 ETF 候选。
- 当前已实测通过的 30 个标的: `AAPL`、`MSFT`、`NVDA`、`AMZN`、`META`、`GOOGL`、`AVGO`、`TSLA`、`AMD`、`NFLX`、`JPM`、`V`、`MA`、`UNH`、`LLY`、`JNJ`、`MRK`、`COST`、`WMT`、`HD`、`XOM`、`CVX`、`COP`、`SLB`、`NEE`、`CAT`、`GE`、`BA`、`DE`、`HON`。

运行命令:

```bash
npm run train:real
```

快速 smoke 验证:

```bash
npm run train:real:smoke
```

等价 Python 命令:

```bash
python3 -m ml.pipelines.real_data --model-id risk_tabular_real_v1 --min-symbols 20 --min-samples 800 --max-samples-per-symbol 80 --compact-feature-metadata --window-mode none
```

如需同时训练深度候选:

```bash
npm run train:real:deep:smoke
python3 -m ml.pipelines.real_data --model-id risk_tabular_real_v1 --min-symbols 20 --min-samples 800 --max-samples-per-symbol 80 --compact-feature-metadata --window-mode window120 --train-deep
```

产物:

- `artifacts/datasets/real_data_v1/dataset.json`
- `artifacts/models/risk_tabular_real_v1/model.pkl`
- `artifacts/models/risk_tabular_real_v1/metrics.json`
- `artifacts/models/risk_tabular_real_v1/model_card.json`
- `artifacts/pipelines/real_data_v1/manifest.json`
- `artifacts/pipelines/real_data_v1/real_readiness_report.json`

如果加 `--train-deep`，manifest 会额外写入:

- `deepCandidates`: `cnn_tcn`、`patch_tst_lite`、`itransformer_lite` 的训练结果。
- `deepCandidateAudit`: 每个深度候选的样本外评估、walk-forward、purged CV、ECE、pinball loss 和候选状态。

当前实测正式真实结果:

- `readiness=pass`，`model_registry.status=approved`。
- 真实样本 2400 条，30 个标的，`sourceStatus={"live": 2400}`。
- `allowSynthetic=false`，`smoke=false`。
- 真实训练前清理旧 demo/synthetic/fallback 行情缓存 1782 行；质量报告中本批 30 个标的 `syntheticRowCount=0`。
- Point-in-Time future leakage 为 0。
- ECE 为 0.0924，pinball loss 为 0.0065，CRPS 为 0.0366，VaR breach rate 为 0.0293。
- walk-forward 2 个窗口，purged CV 3 个 fold。
- `model_judge_v2` 通过: 校准、分布损失、VaR breach、样本外窗口、purged CV 和 no-degraded-samples 全部过门槛。
- 质量覆盖: 复权价格、分红拆股、交易缺口、财报 availableAt、公告 publishedAt、新闻 publishedAt、revision history 和幸存者偏差披露均为 30/30。

真实数据版验收门槛:

- 至少 20 个真实标的。
- 至少 800 条训练样本。
- `allowSynthetic=false`，且样本 `sourceStatus` 不允许出现 `degraded`。
- `historical_prices` 中旧 synthetic/demo/fallback 缓存不能进入训练集。
- 真实训练会在确认真实历史足够后清理本批标的的旧 synthetic/demo/fallback 行。
- 每个标的至少有复权价格来源和 revision history。
- Point-in-Time future leakage 为 0。
- ECE 不高于 0.12，pinball loss 不高于 0.20。
- `model_judge_v2` 必须通过，且注册表只有通过审计的 tabular baseline 才能进入 `approved`。

## 3. 可靠的一定规模算法

用途: 从最小 demo 升级为可复现、可审计、可扩展的风险分布模型训练流程。

默认 universe 包含美股、ETF、A股和基金样例，约 50 个标的。第一阶段目标不是全市场，而是稳定跑通数十到数百个高流动性资产。

快速 smoke 验证:

```bash
npm run train:scale:smoke
```

真实数据优先训练:

```bash
npm run train:scale
```

等价 Python 命令:

```bash
python3 -m ml.pipelines.reliable_scale --fetch-real --min-symbols 30 --min-samples 1200
```

300-600 标的扩展入口:

```bash
npm run train:scale:large:smoke
npm run train:scale:large
```

真实大规模训练入口:

```bash
python3 -m ml.pipelines.reliable_scale --fetch-real --universe large_us_cn --min-symbols 300 --min-samples 12000 --min-rows 1250 --max-samples-per-symbol 40 --compact-feature-metadata --window-mode none --ingest-workers 8 --refresh-events --event-workers 8
```

该入口使用 `large_us_cn` 候选池，目标是覆盖 100-300 个美股/ETF 与 100-300 个 A股/基金标的。真实模式下会按 `real_only` 行数判断是否可用，并清理旧 demo/synthetic/fallback 缓存，避免旧缓存把标的误判为已具备真实历史数据。第一阶段每标的最多抽取 40 个点时样本，300+ 标的合计超过 12000 样本。大规模 tabular 训练启用 `--compact-feature-metadata --window-mode none`，训练集保留 tabular 字段级 PIT metadata，不存长窗口数组，避免生成过大 JSON。

如果真实数据源不可用，可以临时使用:

```bash
python3 -m ml.pipelines.reliable_scale --allow-synthetic --smoke --max-symbols 10 --min-symbols 8 --min-samples 240
```

产物:

- `artifacts/datasets/reliable_scale_v1/dataset.json`
- `artifacts/models/risk_tabular_scale_v1/model.pkl`
- `artifacts/models/risk_tabular_scale_v1/metrics.json`
- `artifacts/models/risk_tabular_scale_v1/model_card.json`
- `artifacts/pipelines/reliable_scale_v1/manifest.json`
- `artifacts/pipelines/reliable_scale_v1/scale_readiness_report.json`

可靠规模算法验收门槛:

- 默认至少 30 个标的。
- 默认至少 1200 条样本。
- Point-in-Time future leakage 为 0。
- 必须包含 train / validation / test 或 shadow 切分。
- ECE 必须不高于 0.12。
- pinball loss 必须不高于 0.20。
- 必须输出 CRPS 和 VaR breach rate。
- walk-forward 至少 2 个窗口。
- purged CV 至少 3 个 fold。
- 预览标的全部完成推理。
- 真实模式下必须输出质量报告，覆盖复权价格、分红拆股、停牌/缺失、`availableAt` / `publishedAt`、revision history 和幸存者偏差说明。

当前真实 large 训练结果:

- `npm run train:scale:large` 已通过: 312 个真实标的，12480 条 live 样本，`allowSynthetic=false`，`smoke=false`，`windowMode=none`，`metadataMode=compact_tabular`。
- 规模 tabular 基线 `risk_tabular_scale_v1` 已通过 `model_judge_v2` 并在 `model_registry` 中为 `approved`。
- 指标: ECE 0.0420，pinball loss 0.0091，CRPS 0.0498，VaR breach rate 0.0775，walk-forward 3 个窗口，purged CV 3 个 fold。
- 真实 large tabular 运行清理旧 demo/synthetic/fallback 行情缓存 2544 行，样本 `sourceStatus={"live": 12480}`。
- 初始事件刷新结果: 312 个请求，226 个成功；插入 disclosure 124、financial_report 124、news_event 226。
- CN/A股/基金披露补齐: 对缺失披露的 163 个标的再次刷新公告/财报证据，成功 163/163，新增 disclosure 163、financial_report 163，错误 0。
- 补齐后质量覆盖: adjusted prices 312/312，dividends/splits 311/312，halts/missing 312/312，filing availableAt 287/312，announcement publishedAt 287/312，news publishedAt 226/312，revision history 312/312，survivorship disclosure 312/312。
- 规模深度候选训练已完成: 312 个真实标的，12480 条 live 样本，`windowMode=window120`。
- 当前 `deepCandidateAudit=fail`: `patch_tst_lite_scale_candidate_v1` 达到 `promotable_candidate`；`cnn_tcn_scale_candidate_v1` 为 `research_candidate`，主要问题是 ECE 0.2835 偏高；`itransformer_lite_scale_candidate_v1` 为 `failed_candidate`，主要问题是 VaR breach rate 0.0088 低于合理区间且 CRPS 0.2610 偏高。深度候选不能进入正式投研卡片，除非后续通过人工 model card 复核、ablation 与重新校准。
- 当前剩余缺口: 25/312 个标的仍缺财报/公告 availableAt 或 publishedAt，86/312 个标的缺新闻 publishedAt，1/312 个标的缺分红拆股记录，且生产级幸存者偏差仍需要 date-stamped universe membership 快照。

可靠规模数据要求:

- 美股/ETF 100-300 个，A股/基金 100-300 个。
- 5-8 年日线数据，第一阶段最少 `min_rows=1250`。
- 收益率统一使用复权价格。
- 分红、拆股、停牌和缺失值需要进入质量报告。
- 财报日期必须区分 `reportDate`、`filingDate`、`availableAt`。
- 公告和新闻必须记录 `publishedAt`，不能用抓取时间代替发布时间。
- 模型推理和特征快照必须有 `revisionId`。
- 生产级训练需要 date-stamped universe membership，降低幸存者偏差。

## 4. 深度模型候选

规模 pipeline 支持候选深度模型:

```bash
python3 -m ml.pipelines.reliable_scale --allow-synthetic --smoke --max-symbols 10 --min-symbols 8 --min-samples 240 --train-deep
```

当前深度模型候选包括:

- `cnn_tcn`
- `patch_tst_lite`
- `itransformer_lite`

这些模型第一阶段作为 candidate，不直接替代表格基线。只有在同样通过 walk-forward、purged CV、校准和 Judge v2 后，才应进入正式投研卡片。

真实数据深度候选入口:

```bash
npm run train:real:deep:smoke
python3 -m ml.pipelines.real_data --model-id risk_tabular_real_v1 --min-symbols 20 --min-samples 800 --train-deep
```

可靠规模深度候选入口:

```bash
npm run train:scale:large:deep:smoke
npm run train:scale:large:deep
python3 -m ml.pipelines.reliable_scale --fetch-real --universe large_us_cn --min-symbols 300 --min-samples 12000 --min-rows 1250 --max-samples-per-symbol 40 --compact-feature-metadata --window-mode window120 --ingest-workers 8 --refresh-events --event-workers 8 --train-deep
```

深度模型必须先作为辅助 encoder 使用，不直接替代风险分布基线。进入正式卡片前必须通过 ablation、校准、样本外和 Judge v2 审计。

深度候选审计状态:

- `failed_candidate`: torch 不可用、训练失败，或缺少样本外指标。
- `research_candidate`: 有样本外指标，但还不能直接进入投研卡片。
- `promotable_candidate`: 同时通过 ECE、pinball、CRPS、VaR breach、walk-forward 和 purged CV 门槛，才允许进入人工 model card 复核。

## 5. 一键验证

```bash
npm run verify
```

该命令会验证:

- 前端构建。
- 后端编译。
- Point-in-Time Feature Store。
- Risk Distribution Engine。
- Calibration & Backtest Validator。
- Token Compression Report。
- 最小 demo pipeline。
- reliable scale smoke pipeline。
- real-only 训练集过滤回归测试。
- FastAPI 研究卡片、报告导出和 Judge v2。

注意: `npm run verify` 不默认拉取网络真实数据，避免日常验证受外部数据源波动影响。真实数据训练用 `npm run train:real` 或 `npm run train:scale` 单独执行。
