# 每日 A 股数据自动采集

每日收盘确认后的链路由独立 worker 运行：采集价格和事件、重建研究数据、生成可用推理结果，并执行只读健康检查。它不会自动激活生产模型。

## 本地常驻运行

开发时可以直接运行：

```bash
PYTHONPATH=src python3 scripts/run_research_worker.py
```

在 macOS 上长期运行时，复制并按本机 Python 路径修改模板：

```bash
cp deploy/com.investment-research.daily-worker.plist.example \
  ~/Library/LaunchAgents/com.investment-research.daily-worker.plist
launchctl bootstrap gui/$(id -u) \
  ~/Library/LaunchAgents/com.investment-research.daily-worker.plist
```

查看状态：

```bash
launchctl print gui/$(id -u)/com.investment-research.daily-worker
python3 scripts/check_daily_research_health.py
```

收盘确认时间为上海时区 15:10。worker 每分钟执行一次轻量规划；同一交易日使用幂等键，不会重复启动完整采集。

## 健康标准

`scripts/check_daily_research_health.py` 输出：

`artifacts/research_lifecycle/daily-data-health.json`

worker 每秒刷新：

`artifacts/research_lifecycle/research-worker-heartbeat.json`

只有以下条件同时满足才是 `healthy`：

- 覆盖账本的 CN 价格覆盖率至少 98%；
- 每个覆盖标的都有 `raw` 与 `qfq` cursor；
- cursor 记录的是真实最后交易日，且距最新应有交易日不超过 1 个交易日；
- cursor 不得落在周末；
- 事件状态为 `events_present` 或 `confirmed_none`。
- worker 心跳在两分钟内更新。

其他情况会显示 `degraded` 和明确 reasons。每日 lifecycle job 会把同样的状态、覆盖率和原因写入 job 账本，供 API 和运维查看。

## 手动恢复

采集异常时先运行健康检查，再仅补价格或完整循环：

```bash
python3 scripts/check_daily_research_health.py
python3 scripts/fetch_free_research_data.py --markets cn --only prices
python3 scripts/run_free_research_cycle.py --decision-context close_confirmed
```

增量采集会重叠最近五个交易日；AKShare 失败时自动尝试 Baostock。两个来源都失败会保留 `fetch_failed`，不会制造价格或把缺失解释成没有事件。
# 每日数据采集运维

每日采集由本机常驻 worker 领取 `research_daily_close` 队列任务后执行。价格请求使用独立子进程：公共数据源在配置的 `provider_timeout_seconds` 内未返回时，该子进程会被终止，主任务继续尝试备用源或下一标的。因此单个网络连接不会无限阻塞每日更新。

默认配置位于 `config/free_research_sources.yaml`：`hard_timeout: true`、单次请求 8 秒、最多两次尝试。采集为增量追加，游标保存在 `var/cn-research/cursors.json`；中断后下一次任务从最新成功游标的重叠交易日继续。

运行后检查：

```bash
python3 scripts/check_daily_research_health.py --as-of YYYY-MM-DD
```

该命令生成 `artifacts/research_lifecycle/daily-data-health.json`。当价格覆盖、游标新鲜度和 worker 心跳满足条件时状态为 `healthy`；否则为 `degraded` 并列出具体原因。CNInfo 的滚动公告窗口会以 `event_coverage:partial` 写入 `warnings`，透明说明范围限制但不否定已完成的每日价格更新。失败不会覆盖上一次有效数据。
