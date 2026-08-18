# 训练数据系统盘上传与校验报告

- 报告时间：2026-08-17 19:08 CST
- 本地项目：`/Users/afa/Documents/investment-research-system`
- 用户确认目标：服务器系统盘
- 既有隔离目标：`/root/investment-research-system/data-staging-20260817/`
- 本 agent 行为：只读检查本地状态并写本报告；未启动服务器、未新建远端连接、未停止或重启同步、未修改 `active.json` 或任何原始数据产物。

## 结论

实际传输会话**确实已经发生并仍在执行**，但本报告不把它记为“上传完成”。只读进程检查在 2026-08-17 19:07 CST 观察到：

- 一个现有 shell 正逐项读取 `artifacts/server_sync_plan_20260817/upload_paths.txt`；
- 子进程为 `rsync -a --partial --inplace --checksum ...`；
- SSH 子进程目标为 `cpod-1u1vc5o26tr3.podtcp.compshare.cn`，远端 rsync 目标为上述系统盘 staging 目录；
- 当时 `var/cn-research` 是正在处理的第一项，rsync 已运行约 50 秒并有非零 CPU 使用。

这些是“同步会话已建立且传输程序处于活动状态”的本地安全证据。根据最新约束，本 agent 没有连接远端、没有查看远端目录，也没有等待进程结束，因此：

- 已传字节数：**未核验**；
- 远端文件数/总量：**未核验**；
- 远端最终 SHA-256：**未核验**；
- 完成状态：**in_progress / completion_unverified**。

实际命令带 `--partial --inplace --checksum`，可以通过重跑同一允许清单续传并按内容比较；没有观察到 `--delete`。`artifacts/server_sync_plan_20260817/README.md` 写的是 `--append-verify`，与实际进程参数不一致；本报告以实际进程参数为准。

## 干净候选范围

以下路径只覆盖长期研究训练输入、必要 PIT/事件/宏观/证券状态/成员股补充证据、训练清单和审计材料。计数和字节数来自 2026-08-17 19:08 CST 的本地只读元数据扫描。

| 候选路径 | 文件数 | 字节数 |
|---|---:|---:|
| `var/cn-research` | 89,586 | 8,490,051,940 |
| `artifacts/cn_financial_disclosures_cninfo` | 6 | 102,389,913 |
| `artifacts/cn_financial_ratios_akshare` | 2 | 41,670 |
| `artifacts/cn_security_lifecycle_akshare` | 2 | 1,043,021 |
| `artifacts/cn_security_master` | 3 | 23,610 |
| `artifacts/cn_event_backfill` | 4 | 447,257,000 |
| `artifacts/cn_event_backfill_full` | 2 | 41,522 |
| `artifacts/cn_security_status_disclosures_cninfo` | 1 | 574 |
| `artifacts/cn_security_name_history_sina` | 2 | 97,315 |
| `artifacts/cn_macro_release_calendar_nbs` | 3 | 591,362 |
| `artifacts/cn_research_auxiliary` | 14 | 18,134,792 |
| `artifacts/cn_trading_status` | 2 | 3,549,590 |
| `artifacts/cn_corporate_actions_detailed` | 2 | 46,155 |
| `artifacts/subagent_financial_pit` | 816 | 43,251,760 |
| `artifacts/subagent_financial_pit_retry` | 353 | 5,005,785 |
| `artifacts/subagent_daily_st_retry` | 168 | 5,457,994 |
| `artifacts/subagent_macro_release` | 24 | 1,477,303 |
| `artifacts/subagent_macro_history_retry` | 647 | 22,428,218 |
| `artifacts/subagent_membership_breadth` | 20 | 11,981,705 |
| `artifacts/subagent_membership_retry` | 27 | 9,895,902 |
| `artifacts/subagent_security_status` | 338 | 18,169,405 |
| `artifacts/local_data_completion_manifest_20260817.json` | 1 | 3,795 |
| `artifacts/long_term_readiness` | 1 | 4,297 |
| `docs/server-data-inventory-20260817.md` | 1 | 18,594 |
| **合计** | **92,025** | **9,180,963,222（8.550438 GiB）** |

`artifacts/local_data_completion_manifest_20260817.json` 是训练数据清单；`docs/server-data-inventory-20260817.md` 与 `artifacts/long_term_readiness/latest.json` 是审计/就绪证据。没有在 `var/cn-research` 中发现 `active.json`。

## 现有同步范围的偏差

现有 `upload_paths.txt` 使用目录级路径，实际本地展开为 92,030 个文件、9,181,174,176 字节。它比上表的干净候选范围多 5 个非训练必需文件、210,954 字节：

| 应排除文件 | 字节数 | 原因 |
|---|---:|---|
| `var/cn-research/catalog.db-wal` | 0 | SQLite 瞬时 WAL，不是长期输入 |
| `var/cn-research/catalog.db-shm` | 32,768 | SQLite 瞬时共享内存文件 |
| `artifacts/subagent_financial_pit_retry/__pycache__/retry_2010_plus.cpython-310.pyc` | 14,812 | Python 缓存 |
| `artifacts/subagent_daily_st_retry/checkpoint.json` | 143,598 | 下载续跑检查点，不是训练输入 |
| `artifacts/subagent_daily_st_retry/__pycache__/retry_daily_st.cpython-310.pyc` | 19,776 | Python 缓存 |

本 agent 遵守“不干扰现有同步”，没有修改清单或终止进程，所以这 5 个文件可能已进入 staging。它们不含凭据，但在最终训练输入清单中应忽略，不应提升到正式快照。旧模型、模型权重、预测、训练输出、通用缓存和日志不在顶层允许清单中。

## 续传与校验方案

1. **续传保持幂等**：仅在现有进程自然结束或中断后，使用同一个 `upload_paths.txt` 和同一 staging 目标重跑 rsync；保留 `--partial --checksum`，不使用 `--delete`，并显式排除上表 5 个文件。重复文件由内容校验跳过，部分文件继续传输。
2. **先做零写入复核**：续传前用相同允许清单执行 `rsync --dry-run --itemize-changes --checksum`。只有清单内差异可以进入正式续传；禁止把整个仓库或 `artifacts/free_research_models`、模型目录、日志目录加入范围。
3. **冻结源清单**：同步自然结束后，对干净候选范围生成逐文件记录：相对路径、字节数、SHA-256；排序后再对清单文件本身计算 SHA-256。当前旧清单大部分 `sha256` 为 `null`，不能替代该步骤。
4. **远端只读比对**：在 staging 目录生成同格式的逐文件大小和 SHA-256，按相对路径排序后与本地清单比较；要求文件数 92,025、总字节 9,180,963,222，且每个 SHA-256 一致。任何源文件在哈希期间发生变化都必须重新传输和重算。
5. **SQLite 一致性**：只校验并保留 `catalog.db`，排除 `catalog.db-wal` 和 `catalog.db-shm`；确认源端无未提交 WAL 后，对远端副本执行只读 `PRAGMA quick_check`。若不满足，不能把 staging 提升为训练快照。
6. **最终幂等证明**：完成后再次运行相同的 `rsync --dry-run --itemize-changes --checksum`；预期无输出。只有此结果与逐文件 SHA-256 同时通过，才能记录为 `uploaded_verified`。

本报告没有改动 `active.json`，也不授权把 staging 目录切换为 active 快照。

## 本次写入与实际结果

- 新写入：`docs/training-handoff/system-disk-upload-report-20260817.md`
- 原始数据产物修改：无
- 服务器启动/连接：本 agent 无
- 新上传进程：无
- 观察到的既有上传：有，系统盘 staging 同步进行中
- 实际上传完成与哈希一致性：未远端核验，不能声明完成
