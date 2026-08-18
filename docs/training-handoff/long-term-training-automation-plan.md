# 长期研究评分卡主模型：训练自动化执行计划

> 状态基线：2026-08-17 本地只读审计。本文是执行计划，不代表已经通过 PIT 门禁，也不授权切换 `active.json`、发布模型或启动下载。

## 1. 结论与执行边界

本文是历史执行计划，当前事实源以 [`../../current-system.md`](../../current-system.md) 和
`config/long_term_training.yaml` 为准。长期主模型必须以季度截面的四项研究任务为中心：

- 主任务：`excess_return_120d`、`excess_return_240d`；
- 主风险任务：`future_max_drawdown_120d`、`future_max_drawdown_240d`；
- 质量持续性和未来波动任务仅保留为独立评分卡或候选实验，不是当前主任务；
- `direction_1d`、`direction_5d`、`return_20d`、`drawdown_20d` 只能进入默认折叠的“短期市场观察”，不得参与长期主模型选优、综合分或替换决策。

当前不能正式训练。`artifacts/long_term_readiness/latest.json` 的状态是 `blocked`，`var/cn-research/active.json` 不存在；已记录的正式阻塞还包括财务 PIT 未证明、历史证券/交易状态不完整、宏观 `published_at` 覆盖不足、历史成员关系未证明。现阶段只允许运行只读审计和不拟合模型的 dry-run。即使 `scripts/run_long_term_training.py --allow-research-only` 能在研究重建上拟合模型，也不能把它称为 dry-run，更不能作为正式训练或发布依据。

硬规则：

1. `PIT_GATE != passed` 时，队列只能进入 `audit_only` 或 `dry_run_complete`，不得创建模型权重、OOF/holdout 预测或 promotion 结果。
2. 正式训练只能读取 hash 校验通过的 `var/cn-research/active.json -> snapshots/<snapshot_id>`；不得读取 `landing/`、下载目录或未绑定快照的 Parquet。
3. 任何 research-only 兼容开关都不得解除正式门禁；正式队列禁止传入 `--allow-research-only`。
4. 本计划不修改或自动交换 `active.json`。快照提升仍由现有 landing 校验和人工批准流程负责。
5. GPU 仅允许物理 `GPU0`，同一时刻最多一个 GPU 训练 stage；CPU 审计/缓存构建可有限并行，但不得与正在下载的进程争用 I/O。

## 2. 现有实现审计与可复用资产

### 2.1 已有、应直接复用

| 能力 | 真实路径 | 当前行为 |
|---|---|---|
| 长期合同 | `config/long_term_training.yaml`、`src/investment_research/training/long_term_config.py` | 当前四项 120/240 日任务、purge/embargo、最终留出、最低 Rank IC 及 60 个 Shadow session；旧 480/960 日描述仅作历史规划，不能作为当前合同 |
| 长期训练入口 | `scripts/run_long_term_training.py` | 校验 active 快照；研究兼容模式可读取 rebuild index；按季度末取样；输出报告与 zstd Parquet 预测 |
| 长期基线 | `src/investment_research/training/long_term_pipeline.py` | constant、industry mean、Ridge、ElasticNet、Random Forest；可选 LightGBM/XGBoost 及 GPU 版本；purged walk-forward、最终 holdout、stress、成本后组合指标 |
| 数据审计 | `scripts/audit_long_term_readiness.py`、`scripts/audit_research_optimization_data.py` | 前者复核 active 文件/hash/PIT 门禁，后者检查全分区样本与 120/240 日标签覆盖 |
| 研究队列 | `scripts/run_research_optimization_queue.py`、`config/research_optimization_queue.json` | 原子写 `queue-status.json`，依次跑 6 个长期任务，固定 `CUDA_VISIBLE_DEVICES=0`、显存比例 0.80、OMP/MKL 各 8 线程 |
| GPU 候选 | `scripts/run_sequence_research_training.py`、`scripts/run_panel_research_training.py`、`src/investment_research/training/sequence_experiment.py` | 现有序列/StockMixer/MASTER 主要面向短周期任务；支持 GPU0、显存比例、batch、早停和最终 `model.pt` |
| 模型审核 | `scripts/evaluate_long_term_promotion.py`、`src/investment_research/training/long_term_promotion.py` | 只读评估；要求 holdout Rank IC、成本后收益及至少 60 个有效 Shadow session；不会自动发布 |
| 产物哈希 | `src/investment_research/training/artifacts.py`、`scripts/index_training_artifacts.py` | SHA-256、大小、引用关系、原子索引和悬空引用检查 |
| Worker 独占锁 | `scripts/run_training_worker.py` | `fcntl.flock` 非阻塞独占锁；单 job 24 小时超时 |

### 2.2 审计中发现的缺口

1. 长期合同只有 120 日波动标签字段，`LabelSet` 没有 `future_volatility_240d`，长期配置和队列也没有 120/240 日波动任务；“长期波动”尚未成为一等目标。
2. `run_research_optimization_queue.py` 只有等待、单次执行和遇错即停，没有 `--dry-run`、队列锁、按 stage 断点续跑、重试分类、退避或严格幂等键。
3. 队列当前允许 `--allow-research-only` 训练；这适合历史研究，但不满足“PIT 未过只 dry-run”的正式自动化要求。
4. `run_long_term_training.py` 每个 target 都重复加载、解析和季度聚合所有分区；没有列裁剪缓存、共享内存映射或一次预载多头复用。
5. 基线训练没有模型 checkpoint；序列/面板 runner 只在全部结束后保存最终 `model.pt`，中途中断会丢失 fold/epoch 进度。
6. 现有深度 runner 的 task contract 不含长期 120/240 日多任务；不能直接把短周期模型改名为长期候选。
7. GPU batch 目前是固定值，没有 OOM 探测和自动回退；温度、主机内存、磁盘、水位和数据加载吞吐没有统一监控/保护。
8. `scripts/generate_trusted_model_card.py` 是旧的风险门禁模型卡，不适合作为新的长期评分卡模型卡。
9. 当前 `evaluate_cross_sectional` 对各目标使用同一套“高分选 Top-K”逻辑；对最大回撤/波动必须先冻结分数方向和风险指标，不能把“更高风险”错误地当成选股收益。

## 3. 目标合同与评分卡

### 3.1 多头结构

共享 PIT 特征干线，按任务分别拟合或共享编码器后分头输出：

| 头 | 标签 | 输出语义 | 主评估 |
|---|---|---|---|
| 相对收益 120/240 日 | `excess_return_120d/240d` | 越高越好，相对宽基基准；ETF 只作宽基/风格上下文，不混入股票 alpha 标签 | Spearman Rank IC/ICIR、Top-K 成本后超额、Top-Bottom spread、换手、容量 |
| 回撤 120/240 日 | `future_max_drawdown_120d/240d` | 统一转换为非负风险严重度 `risk=-drawdown`，越高风险越大 | 风险 Rank IC、最差分位召回、Pinball/MAE、风险回避组合的回撤改善 |
| 长期波动 120/240 日 | `future_volatility_120d/240d` | 年化实现波动，越高风险越大；必须冻结交易日数、复权和缺失日规则 | 风险 Rank IC、MAE、分位覆盖率、校准误差 |
| 质量持续性 4/8 季 | `future_quality_persistence_4q/8q` | 未来 PIT 季度质量信号的持续性，不从当前期标签泄漏 | Rank IC/ICIR、跨季度稳定性、行业/年份切片 |

评分卡输出继续采用现有契约：`long_term_quality`、`growth_stability`、`valuation_position`、`shareholder_return`、`long_term_risk`、`evidence_completeness`。其中证据型当前分数和学习型未来目标必须分字段保存；当前 `score_type=pit_evidence_scorecard_not_trained_label` 不得改成训练预测。

### 3.2 数据和验证不变量

- 决策单位：`symbol_quarter_end`，每个标的每季度保留最后一个可用交易日。
- 宽基基准：在 run manifest 中冻结 symbol、复权策略和版本；120/240 日超额必须使用相同可交易日期交集。
- 全部特征满足 `available_at <= decision_time`；财报 revision 只在当时已知版本上展开。
- 训练/验证/holdout 全部按时间分割；预处理器只在相应训练 fold 拟合。
- 复用 `config/long_term_training.yaml` 当前 `purge_periods=4`、`embargo_periods=1`、`final_holdout_periods=8`、`stress_periods=4`；最长标签扩展后，代码必须验证 purge 覆盖所有头的最长 horizon。
- 最终 holdout 冻结且只评估一次。超参选择只看 development OOF；若看过 holdout 后改模型，必须生成新 dataset/run hash，并将旧 holdout 标为已消费。
- 短周期 1/5/20 日结果存放在 `auxiliary/`，不能进入长期模型的 champion 比较表或综合评分权重。

## 4. 分阶段模型队列

每个 stage 的输入都是同一个 `dataset_hash + feature_contract_hash + label_contract_hash + split_hash`。任何 hash 改变都产生新 `run_id`，不得复用旧结果。

### Stage 0：PIT 审计与 dry-run

- 校验长期 YAML、依赖版本、GPU0 可见性、磁盘/内存预算。
- 运行 `audit_long_term_readiness.py` 和 `check_research_snapshot.py`。
- 解析 manifest 但不读训练矩阵，列出预计分区、行数、字段、标签覆盖、stage DAG、输出路径和资源预算。
- 只有所有正式 PIT 检查通过，才写 `gate/passed.json`；否则写 `dry-run-report.json` 并以专用退出码 20 结束，队列状态为 `dry_run_complete_blocked`，不是失败重试。

### Stage 1：可解释 baseline

- constant、industry mean、Ridge、ElasticNet；固定 seed 42。
- 用于验证标签方向、fold、成本模型、评分卡映射和审计链，不以表现最好为目标。
- 每个 target/fold 独立输出 checkpoint 和 OOF shard；全头通过完整性检查后合并。

### Stage 2：树模型主候选

- Random Forest 作为非线性 CPU 参考。
- LightGBM CPU 为必跑候选；若本机 LightGBM GPU 构建可用，再跑 `lightgbm-gpu`，否则记录明确 fallback，不静默改变算法。
- XGBoost 作为次级对照，不因可用就扩大无界搜索。
- 搜索预算采用冻结的小网格或 Optuna 等价的固定 trial manifest：第一轮每头 12–24 trials，先用 OOF 选 3 个配置，再跑 3 seeds；不触碰最终 holdout。

### Stage 3：GPU 深度候选

- 先实现“季度横截面多任务 MLP”作为最小 GPU sanity candidate，再评估时间序列编码器。
- 候选顺序：MLP -> TCN/PatchTST -> StockMixer -> MASTER/iTransformer。后一模型只有在前一阶段的数据吞吐和 OOF 稳定性达标时才排队。
- 现有 `run_sequence_research_training.py` 和 `run_panel_research_training.py` 只能作为实现素材；需先扩展长期 task/label/fold contract，禁止直接用其短周期任务结果参加长期选优。
- 深度候选至少 3 seeds；早停看 development validation，多头 loss 权重在 run config 中冻结。缺标签用 mask，不用 0 填充。
- 单张 GPU0 串行跑；CPU 预取只服务当前 GPU job。Tree CPU job 与 GPU job 默认不并跑，除非试跑证明主存、I/O 和温度都在安全水位。

### Stage 4：消融、稳健性和一次性最终测试

- 按现有特征组逐组加入：质量/资产负债表、现金流/成长、行业相对估值、股东回报、行业/市场、宏观、事件/公司行为。
- 对缺少正式发布时间证明的组直接标为 unavailable，不用研究假设补齐。
- 报告年份、行业、市场状态、成本 10/15/30 bps、Top-K 10/20/30、标签覆盖和最近窗口敏感性。
- 冻结单一 champion 配置后才运行最终 holdout；同一 head 的 holdout 只消费一次。

### Stage 5：模型卡、Shadow 和人工审核

- 生成长期专用模型卡、全产物哈希索引和 promotion 只读报告。
- 至少积累 `minimum_shadow_sessions=60` 个独立有效 session。
- 自动化最多写 `candidate_for_review`；不得自动改 registry 的 active/approved 指针。

## 5. 资源编排：高利用率但不盲目占满

仓库盘点记录的目标服务器为单张 NVIDIA RTX 4090 24,564 MiB；只用 GPU0。CPU 核数和主存没有可信实测记录，启动时必须探测，不能按文档猜测。

### 5.1 GPU0 策略

- 环境固定 `CUDA_DEVICE_ORDER=PCI_BUS_ID`、`CUDA_VISIBLE_DEVICES=0`；日志保存物理 GPU UUID、驱动、CUDA、PyTorch、LightGBM/XGBoost build 信息。
- 初始进程显存上限 0.80，正常稳定后允许到 0.85，硬上限 0.88；至少保留约 3 GB 给 CUDA context、抖动和监控。现有 0.80 默认可直接作为首轮值。
- 混合精度优先 BF16（设备支持时），否则 FP16+GradScaler；验证和关键风险指标以 FP32 聚合。
- `batch` 自调：对第一个真实 fold 做 32 -> 64 -> 128 -> 256 的指数探测；每档执行前向、反向和 optimizer step 3 次。OOM 时清理 CUDA cache 并退到最大成功 batch 的 80%，再向 8 的倍数取整。将结果写入 `resource-profile.json`，相同 input shape/GPU UUID 才可复用。
- 面板模型调的是 `batch_dates` 而不是普通样本 batch；按 `batch_dates=1,2,4,8...` 探测。禁止让单 batch 覆盖全部日期或全部历史。
- 目标 GPU 利用率是训练段 70%–95%，不是持续 100%；若 GPU 利用率低而 CPU/I/O 已满，应优化预取而不是继续加显存。

### 5.2 数据预载、内存映射与 DataLoader

在 Stage 0 后增加一次内容寻址缓存：

```text
artifacts/long_term_training/runs/<run_id>/cache/<dataset_hash>/
  features.f32.mmap
  labels.f32.mmap
  label_mask.u8.mmap
  row_index.parquet
  feature_order.json
  cache-manifest.json
```

- 从 `sample_parquet_ref` 读取时做列裁剪，只读 symbol/date/industry、目标标签、质量 mask 和冻结特征列；不要反复 `to_pylist()` 加载全表。
- 缓存先写 `.tmp`，完成后 fsync、计算 SHA-256 并原子 rename；`cache-manifest.json` 绑定数据/特征/标签 hash、shape、dtype、字节序和构建代码版本。
- 多 target 共用一份只读 feature mmap，各 head 只加载自己的 label/mask；季度索引在一次预处理中生成。
- 小于可用主存 35% 的热索引可预载，大矩阵只 mmap；操作系统页缓存负责复用。不得同时保留 Arrow table、Python dict 行列表和 NumPy 完整副本。
- DataLoader 初始 `num_workers=min(8, max(2, physical_cores//2))`、`pin_memory=True`、`persistent_workers=True`、`prefetch_factor=2`；主存达到 80% 或 major page fault 激增时先把 prefetch 降为 1，再减少 worker。
- PyTorch job 中设 `torch.set_num_threads(max(1, (physical_cores-num_workers)//2))`，并将 `OMP_NUM_THREADS`/`MKL_NUM_THREADS` 同步到该值，避免 DataLoader 与 BLAS 过度订阅。
- LightGBM/Random Forest CPU stage 不使用 DataLoader；线程从 `min(physical_cores-2, 16)` 起步，保留至少 2 个物理核给系统、压缩和监控。现有硬编码 8 线程作为未知硬件时的安全 fallback。

### 5.3 热量、内存、磁盘和 I/O 保护

每 5 秒采集 GPU 温度/功耗/利用率/显存、CPU load/温度、RSS、cgroup memory、swap、磁盘剩余、读写吞吐和 batch latency；每 60 秒落一条 JSONL，异常事件立即落盘。

默认水位需在服务器首轮校准后写入 run config：

- GPU 温度：`>=78°C` 告警；`>=83°C` 连续 60 秒时 batch 降一档或功耗限额降 10%；`>=87°C` 或驱动报错时安全 checkpoint 并暂停。恢复需 `<78°C` 连续 5 分钟，避免抖动。
- 主存：RSS+cgroup 使用率 `>=75%` 告警，`>=85%` 降低预取/worker，`>=92%` 安全 checkpoint 并暂停；出现 OOM kill 记录为资源失败，不能直接原 batch 无限重试。
- swap：持续换入换出或 swap 使用超过 10% 即降并发；深度训练不得靠 swap 维持吞吐。
- 磁盘：开跑前可用空间至少 `max(15 GB, 2 * 预计本 run 产物大小)`；低于 10 GB 不启动新 stage，低于 5 GB checkpoint 后暂停。盘点服务器仅约 22 GB 可用，因此同步数据后必须重新测量，不能预设足够。
- I/O：若下载进程存在，训练队列默认等待；不得终止、renice 或修改下载进程。经人工明确允许并且磁盘等待低于 20% 时，才可让纯 CPU 缓存任务与下载并行。

## 6. 自动队列、幂等、锁、重试和续跑

### 6.1 Run identity 与目录

`run_id = lt-<UTC>-<dataset_hash[:12]>-<config_hash[:12]>-<code_hash[:12]>`。目录固定：

```text
artifacts/long_term_training/runs/<run_id>/
  run-manifest.json
  gate/
  cache/
  stages/<stage_id>/attempt-0001/
  checkpoints/<target>/<model>/<seed>/<fold>/
  predictions/
  metrics/
  logs/
  resource/
  model-card.json
  artifact-index.json
  SUCCESS
```

所有 JSON 状态均 `.tmp -> fsync -> os.replace`。`SUCCESS` 只在报告、引用和 hash 全部验证后写入；看到部分文件不等于 stage 完成。

### 6.2 双层锁

- 队列锁：`var/locks/long-term-queue.lock`，使用 `fcntl.flock(LOCK_EX|LOCK_NB)`；防止两个 orchestrator 运行同一 DAG。
- GPU 锁：`var/locks/gpu0-training.lock`；每个 GPU stage 持有，CPU-only 审计不持有。
- 锁文件记录 pid、hostname、run_id、started_at，但是否存活由 flock 判断，不能仅凭旧 pid 文件删除锁。
- 不复用 `scripts/run_training_worker.py` 当前 job 命令，除非先把 worker 改为调用新的长期 orchestrator；它目前调用的是 `run_cn_research_demo.py`。

### 6.3 幂等键和状态机

stage key 包含：`stage_name,target,model,seed,fold,dataset_hash,config_hash,code_hash,hyperparameter_hash`。状态只允许：

```text
queued -> running -> succeeded
                  -> retry_wait -> running
                  -> failed_terminal
queued -> blocked_gate
queued -> skipped_reused
```

续跑时只有 `SUCCESS + artifact-index 校验通过 + key 完全一致` 才复用；缺文件、hash 不符、输入 hash 改变都新建 attempt，不覆盖旧 attempt。

### 6.4 Checkpoint 规范

每个深度 fold 至少保存 `last.pt` 和 `best.pt`，内容包括：

- model、optimizer、scheduler、AMP scaler state；
- epoch、global_step、best_metric、patience；
- Python/NumPy/PyTorch CPU/PyTorch CUDA RNG state；
- sampler epoch/offset；
- feature order、normalizer、label mask、split hash；
- dataset/config/code/hyperparameter hash；
- GPU UUID、库版本和 deterministic flags。

checkpoint 先写临时文件再原子替换，并附 `.sha256`。恢复时任一 hash 不匹配立即拒绝；只允许从完整 epoch 边界恢复，避免样本重复/遗漏无法审计。Tree 模型按 fold/trial 保存 joblib/native model 和 predictions shard；成功的 fold 不重跑。

### 6.5 重试策略

- 可重试：瞬时 I/O、文件句柄不足、GPU OOM（batch 降一档）、GPU 温度保护、worker 被 SIGTERM 后存在有效 checkpoint。
- 不可重试：PIT/泄漏/数据 hash 失败、schema 不符、NaN 指标、目标方向不明、checkpoint hash 不符、holdout 已被不合规消费。
- 自动重试最多 2 次，退避 60 秒、300 秒；第三次进入 `failed_terminal`。同一错误签名连续两次不得继续扩大资源。
- `blocked_gate` 不计失败、不自动重试；等待新的、经批准的 active snapshot 后生成新 run_id。

## 7. 可复现命令

以下命令从项目根目录执行。`python3 -m pip install -e ".[train,dev]"` 只在新环境初始化时执行；生产 run 必须把 `python -VV`、`pip freeze` 和 GPU 信息写入 manifest。

### 7.1 当前允许：只读审计和合同验证

```bash
cd /Users/afa/Documents/investment-research-system
export PYTHONHASHSEED=42
export PYTHONPATH="$PWD/src"

python3 scripts/audit_long_term_readiness.py \
  --project-root "$PWD" \
  --output artifacts/long_term_readiness/latest.json

python3 -c 'from pathlib import Path; from investment_research.training.long_term_config import load_long_term_training_config as load; c=load(Path("config/long_term_training.yaml")); print(c.canonical_hash())'
```

预期：当前 readiness 返回码为 2、状态 `blocked`。这是正确的 fail-closed 结果，不应触发训练重试。

### 7.2 当前研究数据覆盖审计（只读数据、写审计报告）

先从已选 rebuild index 的 `contexts.close_confirmed.sample_manifests` 生成冻结 manifest list；现有可引用的研究重建之一是：

```text
artifacts/free_research_rebuild/aligned-20260817-final-v2/rebuild-2026-08-14-1563c6f013cb.json
```

生成 list 必须由待实现 orchestrator 完成并记录 rebuild index 的 SHA-256；不要手工改 index。随后执行现有审计：

```bash
python3 scripts/audit_research_optimization_data.py \
  --sample-manifest-file artifacts/long_term_training/runs/<run_id>/gate/sample-manifests.json \
  --object-store var/cn-research/parquet \
  --output artifacts/long_term_training/runs/<run_id>/gate/data-audit.json \
  --all-partitions
```

这只能证明研究样本结构和标签覆盖，不等于正式 PIT 门禁通过。

### 7.3 最小改造完成后的统一 dry-run

```bash
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 \
python3 scripts/run_long_term_automation.py \
  --mode dry-run \
  --config config/long_term_training.yaml \
  --data-root var/cn-research \
  --object-store var/cn-research/parquet \
  --run-root artifacts/long_term_training/runs
```

必须保证：门禁未过时不产生 `.pt`、`.joblib` 或 predictions，只生成 manifest、审计和资源计划。

### 7.4 PIT 全过后才允许的正式训练

```bash
CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 \
INVESTMENT_RESEARCH_GPU_MEMORY_FRACTION=0.80 \
OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 \
python3 scripts/run_long_term_automation.py \
  --mode formal \
  --config config/long_term_training.yaml \
  --data-root var/cn-research \
  --object-store var/cn-research/parquet \
  --run-root artifacts/long_term_training/runs \
  --resume \
  --seed 42 --seed 43 --seed 44
```

统一入口实现前，可用现有单 target 命令验证 baseline，但也必须在正式 active gate 通过后，且不得传 `--allow-research-only`：

```bash
python3 scripts/run_long_term_training.py \
  --samples artifacts/long_term_training/runs/<run_id>/gate/sample-manifests.json \
  --config config/long_term_training.yaml \
  --data-root var/cn-research \
  --object-store var/cn-research/parquet \
  --target excess_return_240d \
  --output artifacts/long_term_training/runs/<run_id>/stages/baseline/excess_return_240d.json \
  --predictions-output artifacts/long_term_training/runs/<run_id>/predictions/excess_return_240d.parquet
```

### 7.5 训练后审计与 promotion

```bash
python3 scripts/index_training_artifacts.py \
  --root artifacts/long_term_training/runs/<run_id> \
  --output artifacts/long_term_training/runs/<run_id>/artifact-index.json \
  --kind long_term_training_artifact \
  --retention-days 730

python3 scripts/evaluate_long_term_promotion.py \
  --report artifacts/long_term_training/runs/<run_id>/metrics/champion-report.json \
  --shadow-directory artifacts/research_shadow \
  --config config/long_term_training.yaml \
  --output artifacts/long_term_training/runs/<run_id>/promotion.json
```

promotion 返回 `candidate_for_review` 也只进入人工评审，不自动发布。

## 8. 验收指标

### 8.1 数据/PIT 硬门禁

- `audit_long_term_readiness.status == ready_for_long_term_training`；active manifest 的所有文件 SHA-256、大小和引用验证通过。
- `data_tier == formal_pit`；泄漏错误、未来事件/价格、跨快照混用均为 0。
- 财务 PIT 覆盖不低于现有合同的 95%，并且是 `pit_verified=true`；宏观、交易状态、证券生命周期、历史成员关系分别通过，而不是用总体覆盖率掩盖。
- 标签覆盖按“可成熟样本”计算：内部空洞为 0；末端自然未成熟单独统计。120/240 日收益和回撤/波动均必须给出 present/eligible 比例和日期边界。
- quality 4q/8q 标签必须来自之后的 PIT 季度快照；没有足够未来季度时保持缺失。

### 8.2 模型硬门禁

- 每个 120/240 日相对收益头：holdout Rank IC `>=0.02`（沿用配置），成本后 Top-K 超额 `>0`，Top-Bottom spread `>0`；至少 70% 的可评估年份 Rank IC 为正。
- 每个回撤/波动头：风险严重度 Rank IC `>=0.02`；最差 20% 风险召回和 Pinball/MAE 均优于训练期常数基线至少 5%；风险回避组合的 holdout 最大回撤不劣于未过滤组合，且要报告收益代价。
- quality 4q/8q：holdout Rank IC `>=0.02`，至少 70% 可评估年份为正，行业中位 Rank IC 不为负。
- 稳定性：3 seeds 的关键 Rank IC 标准差 `<=0.01` 或均值的 50%（取更宽者）；任何 head 出现 NaN、方向翻转或单一行业贡献超过 40% 都阻断。
- 成本/容量：10/15/30 bps 三档全报告；15 bps 为主口径。`capacity_estimate=None` 时不得声称可部署。
- 深度候选只有在同一 split/hash 上，相比 LightGBM 的 development OOF Rank IC 提升 `>=0.005`，并且 holdout 不触发任何风险门禁，才进入候选；否则选择更简单模型。
- 至少 60 个独立有效 Shadow session；模型卡、预测、checkpoint、环境和审计索引无悬空/hash 错误。

这些是最低门槛，不是优化目标。不得以一个强任务抵消另一个核心任务失败；长期 champion 是满足全部硬门禁后的 Pareto/简洁性选择，不是单一加权分数冠军。

## 9. 长期模型卡与审计哈希

新增 `long-term-model-card-v1`，至少包含：

- 目标、适用周期、股票池、宽基基准、不可用于实盘的声明；
- snapshot id/manifest hash、dataset/feature/label/split/config/code/environment hash；
- 样本数、标的数、日期范围、各标签 eligible/present/末端未成熟、PIT 缺口；
- 模型族、超参、seed、fold、checkpoint、输入 shape、资源画像；
- OOF/holdout/stress 的按任务、年份、行业、市场状态和成本指标；
- score 方向、缺失 mask、校准、阈值、短期辅助隔离说明；
- 与 baseline/LightGBM 的差异、失败试验、已消费 holdout 标记；
- 温度/OOM/重试/降 batch/GPU fallback 等运行事件；
- Shadow session、promotion 结果、限制、回滚候选和人工批准字段。

审计 hash 层级：

```text
source file hashes
  -> active snapshot manifest hash
  -> dataset hash
  -> feature + label + split contract hashes
  -> stage input hash
  -> checkpoint/model/prediction/report hashes
  -> artifact-index hash
  -> model-card hash
```

代码 hash 在没有可用 Git 元数据时，使用纳入运行的 Python/YAML 文件清单及逐文件 SHA-256 生成 Merkle 风格摘要，并在模型卡标注 `source_control_commit_unavailable`，不能伪造 commit id。

## 10. 预计资源与时间估算

### 10.1 资源建议

| 场景 | CPU | 主存 | GPU | 磁盘空闲 |
|---|---:|---:|---:|---:|
| 审计/季度缓存/baseline | 8 物理核起，16 核较好 | 最低 32 GB，推荐 64 GB | 不需要 | 至少 15 GB，推荐 30 GB |
| LightGBM 小网格 | 12–16 物理核 | 推荐 64 GB | 可选 GPU0 | 30 GB |
| 多任务深度/面板候选 | 8–16 物理核供预取 | 推荐 64 GB；全池面板建议 96 GB | GPU0 RTX 4090 24 GB | 30–50 GB NVMe |

现有服务器记录只确认 GPU0 24 GB 和当时磁盘约 22 GB 可用，没有可靠 CPU/主存实测。正式启动前必须把实际探测结果写入 `resource-profile.json`；若同步数据后空间低于门槛，先扩盘或选择外部只读数据盘，不清理仍被引用的产物。

### 10.2 先测后估的方法

Stage 0 运行三个不消费 holdout 的 pilot：

1. 顺序读取 5% 分区，测 Parquet 解压/列裁剪吞吐 `R_io`（GB/min）和缓存构建 `R_row`（rows/s）；
2. 选第一个 development fold，跑一个 LightGBM 配置，得到 `T_tree_pilot`；
3. 深度模型跑 200 step，得到稳定 `T_step`、最大安全 batch、GPU 利用率和峰值显存。

估算公式：

```text
T_cache = input_selected_GB / R_io + rows / R_row
T_tree  = T_tree_pilot * (总 fold-config-seed 数 / pilot 数) * 数据量缩放系数
T_deep  = T_step * 每 epoch steps * 预计 early-stop epochs * fold * seed * candidate 数
T_total = 1.3 * (T_cache + T_tree + T_deep + T_eval)
```

`1.3` 是 checkpoint、评估、重试和温控余量。每个 stage 完成后用实际耗时更新剩余 ETA，保存 p50/p90，不显示虚假精确到分钟的 ETA。

在 167 标的、约 806,590 个日样本经季度聚合、单张 RTX 4090 的现有量级下，初始排期可按以下保守范围准备，首个 pilot 后必须替换：

- 审计与共享缓存：0.5–2 小时；
- baseline 六至八个头：1–4 小时；
- LightGBM 小网格、3 seeds：4–16 小时；
- 1 个深度候选完整 folds、3 seeds：8–36 小时；
- 4 个深度家族全部跑完：2–6 天。

先跑 baseline 和 LightGBM；若简单模型已达标且深度 pilot 没有明确 OOF 增益，应停止后续深度队列，节省 GPU 时间。

## 11. 最小改造清单

按优先级实施，避免重写现有训练栈：

1. 新增 `scripts/run_long_term_automation.py`：`--mode dry-run|formal`、PIT fail-closed、DAG、双锁、状态机、重试、resume、资源保护；复用现有 audit、baseline、promotion 和 artifact index。
2. 修改 `scripts/run_research_optimization_queue.py`：默认不再通过 `--allow-research-only` 进入正式路径；若保留历史研究模式，明确命名 `--mode research-experiment` 并输出到隔离目录。
3. 修改 `src/investment_research/training/models.py`、标签生成代码、`config/long_term_training.yaml` 和 `long_term_config.py`：补 `future_volatility_240d`，把 120/240 波动加入长期主任务并校验方向/成熟度。
4. 新增共享季度 mmap cache builder；修改 `run_long_term_training.py` 支持 `--cache-manifest`，一次加载多 target，避免重复 Python 行对象。
5. 修改 `long_term_pipeline.py`：按收益/风险/质量分离 evaluator，冻结风险分数方向，增加 MAE/Pinball/分位召回/波动校准；保留现有 portfolio evaluator 给收益头。
6. 扩展 `run_sequence_research_training.py`/`run_panel_research_training.py` 或新增长期专用 deep runner：长期 tasks、多头 mask、GPU device、AMP、batch autotune、DataLoader、fold/epoch checkpoint 与 resume。
7. 提取 `training/resource_guard.py`：GPU0 锁、nvidia-smi/psutil 指标、内存/温度/磁盘水位和安全暂停；依赖不可用时 fail-closed 或记录降级，不能静默无监控长跑。
8. 新增长期模型卡生成器；沿用 `scripts/index_training_artifacts.py` 做最终闭包校验。
9. 修改 `src/investment_research/workers/training.py`：新增长期 job type 并调用统一 orchestrator；保持 worker 的独占锁和 24 小时超时，但允许 orchestrator checkpoint 后由下一 job resume。
10. 增加测试：PIT 未过绝不调用 fit、dry-run 无权重产物、GPU 仅 0、OOM 降 batch、温控暂停、锁互斥、hash 不同不复用、checkpoint RNG 恢复、短期任务不进入 champion、风险方向正确、holdout 只消费一次。

## 12. 上线前检查表

- [ ] `active.json` 由独立数据流程提升，训练流程未修改它；
- [ ] readiness 所有 check passed，且人工复核 PIT 证据；
- [ ] dry-run 不产生模型/预测；formal 在 blocked gate 下无法启动；
- [ ] 数据/特征/标签/split/config/code/environment hash 齐全；
- [ ] GPU0 独占、显存自调、温度/内存/磁盘保护演练通过；
- [ ] baseline、LightGBM、深度候选按顺序运行，短周期辅助完全隔离；
- [ ] checkpoint 中断恢复结果与不中断运行在容差内一致；
- [ ] 所有核心 head 分别通过验收，不用平均分掩盖失败；
- [ ] 最终 holdout 仅消费一次，模型卡标记其状态；
- [ ] artifact index 无缺失、hash mismatch 或 dangling reference；
- [ ] 60 个有效 Shadow session 和人工审核完成；
- [ ] 没有终止、修改或争用任何正在下载的进程。
