# 失败案例集

## 新闻时间缺失

没有可验证 `published_at` 的新闻不能进入 PIT 特征。系统记录 provider normalization failure，Agent 继续使用其他证据；若事件来源覆盖不足则 gate 为 hold。

## 财报数据冲突

两个权威 revision 对同一数字不一致时，两条 Evidence 均保留并建立相反 Claim。系统不自动平均数字，正式 Claim 保持 proposed，报告降级并要求人工审核。

## Reference 缺失

benchmark、sector 或 style reference 先执行同市场向后 as-of fallback。最终特征覆盖低于 75% 时模型推断被阻断；达到阈值但发生插补时报告显示 missing features 与风险标志。

## 模型版本失效

primary artifact 缺失、hash 不符或版本不匹配时自动尝试 champion fallback 并记录工具审计。fallback 同样不可用时风险概率为 unavailable，语言模型不得补造数值。

## 视觉解析不可靠

模糊、裁切或低分辨率图表在 OCR、表格文本与视觉候选无法交叉一致时标记 `needs_visual_review`。数字不会成为 Evidence。腾讯年报实验把错误数字拒答率作为硬指标。

## 网络不可用

在线 provider 失败后只允许读取带抓取时间和 hash 的真实缓存。页面显示 stale/cache 状态；没有真实缓存时返回 unavailable，不切换到 synthetic。

## 证据不足

少于两条证据、没有权威来源、引用 ID 无效或反方证据未处理时，QualityGate 输出 warn、hold 或 block。hold/block 结束 AgentRun 为 abstained，且不创建正式报告。
