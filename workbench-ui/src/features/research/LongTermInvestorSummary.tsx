import type { LongTermModelCandidate, LongTermModelReading, LongTermModelRegistryEntry, LongTermScorecardResponse, ResearchAcceptanceReport, ResearchForecastBundle } from "../../api/types";

type Props = {
  forecast?: ResearchForecastBundle;
  acceptance?: ResearchAcceptanceReport;
  scorecard?: LongTermScorecardResponse;
  language: "zh-CN" | "en-US";
};

function pct(value: number | undefined) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function modelRange(reading: LongTermModelReading | undefined, language: "zh-CN" | "en-US") {
  // The competition homepage shows only a plain-language observation, never
  // the raw q10/q50/q90 quantiles.  Report readiness only here; the
  // professional details surface the technical values.
  if (!reading || reading.q50 == null) return language === "zh-CN" ? "读数尚未生成" : "Reading not generated";
  const centre = reading.q50;
  if (reading.task?.startsWith("excess_return")) {
    if (centre >= 0.04) return language === "zh-CN" ? "相对基准偏强（观察）" : "Above benchmark (observation)";
    if (centre <= -0.04) return language === "zh-CN" ? "相对基准偏弱（观察）" : "Below benchmark (observation)";
    return language === "zh-CN" ? "相对基准中性（观察）" : "Near benchmark (observation)";
  }
  if (centre <= -0.12) return language === "zh-CN" ? "潜在下跌幅度偏大（观察）" : "Larger potential decline (observation)";
  if (centre <= -0.05) return language === "zh-CN" ? "潜在下跌幅度中等（观察）" : "Moderate potential decline (observation)";
  return language === "zh-CN" ? "潜在下跌幅度偏小（观察）" : "Smaller potential decline (observation)";
}

function shortHash(value: string | null | undefined) {
  return value ? value.slice(0, 12) : "—";
}

function dateRangeLabel(value: Record<string, unknown> | null | undefined, language: "zh-CN" | "en-US") {
  if (!value) return language === "zh-CN" ? "评估文件未记录" : "Not recorded in evaluation";
  const start = typeof value.start === "string" ? value.start : null;
  const end = typeof value.end === "string" ? value.end : null;
  if (!start || !end) return language === "zh-CN" ? "评估文件未记录" : "Not recorded in evaluation";
  const granularity = typeof value.granularity === "string" && value.granularity !== "day"
    ? ` (${value.granularity})`
    : "";
  return `${start} → ${end}${granularity}`;
}

function modelTaskLabel(task: string, language: "zh-CN" | "en-US") {
  const labels: Record<string, [string, string]> = {
    excess_return_120d: ["相对表现（约6个月）", "Relative performance (6m)"],
    excess_return_240d: ["相对表现（约12个月）", "Relative performance (12m)"],
    future_max_drawdown_120d: ["潜在回撤（约6个月）", "Potential drawdown (6m)"],
    future_max_drawdown_240d: ["潜在回撤（约12个月）", "Potential drawdown (12m)"],
  };
  return labels[task]?.[language === "zh-CN" ? 0 : 1] ?? task;
}

function metricLabel(key: string, language: "zh-CN" | "en-US") {
  const labels: Record<string, [string, string]> = {
    rank_ic: ["Rank IC", "Rank IC"],
    rank_icir: ["ICIR", "ICIR"],
    risk_rank_ic: ["风险排序 Rank IC", "Risk rank IC"],
    interval_coverage: ["区间覆盖", "Interval coverage"],
    top_k_mean_excess_return_after_cost: ["Top-K 成本后相对收益", "Top-K excess return after cost"],
    top_bottom_spread_after_cost: ["Top-Bottom 成本后差值", "Top-Bottom spread after cost"],
    risk_top_k_mean_excess_return_after_cost: ["风险排序 Top-K 成本后收益", "Risk-ranked Top-K return after cost"],
    risk_top_bottom_spread_after_cost: ["风险排序 Top-Bottom 成本后差值", "Risk-ranked Top-Bottom spread after cost"],
    max_drawdown_after_cost: ["成本后最大回撤", "Max drawdown after cost"],
    risk_max_drawdown_after_cost: ["风险排序成本后最大回撤", "Risk-ranked max drawdown after cost"],
    turnover: ["换手", "Turnover"],
    risk_turnover: ["风险排序换手", "Risk-ranked turnover"],
    capacity_estimate: ["容量估计", "Capacity estimate"],
    risk_capacity_estimate: ["风险排序容量估计", "Risk-ranked capacity estimate"],
    pinball_loss: ["Pinball Loss", "Pinball loss"],
    p50_mae: ["中位数 MAE", "P50 MAE"],
    year_rank_ic: ["分年度 Rank IC", "Rank IC by year"],
    risk_year_rank_ic: ["风险排序分年度 Rank IC", "Risk-ranked Rank IC by year"],
    industry_rank_ic: ["分行业 Rank IC", "Rank IC by industry"],
    risk_industry_rank_ic: ["风险排序分行业 Rank IC", "Risk-ranked Rank IC by industry"],
    regime_metrics: ["分市场状态", "By market regime"],
    risk_regime_metrics: ["风险排序分市场状态", "Risk-ranked by market regime"],
    data_completeness_rank_ic: ["按数据覆盖 Rank IC", "Rank IC by data coverage"],
    risk_data_completeness_rank_ic: ["风险排序按数据覆盖 Rank IC", "Risk-ranked Rank IC by data coverage"],
  };
  return labels[key]?.[language === "zh-CN" ? 0 : 1] ?? key;
}

function formatTechnicalMetric(key: string, value: number | Record<string, number>, language: "zh-CN" | "en-US") {
  if (typeof value !== "number") {
    return `${Object.keys(value).length} ${language === "zh-CN" ? (key === "regime_metrics" ? "类" : "组") : (key === "regime_metrics" ? "regimes" : "groups")}`;
  }
  return key.includes("coverage") || key.includes("return") || key.includes("spread") || key.includes("drawdown") || key.includes("turnover") || key.includes("rank_ic")
    ? `${(value * 100).toFixed(2)}%`
    : value.toFixed(4);
}

function RegistryEntry({ entry, language }: { entry: LongTermModelRegistryEntry; language: "zh-CN" | "en-US" }) {
  const metrics = Object.entries(entry.holdout_metrics ?? {});
  const missingMetrics = Object.entries(entry.evaluation_metric_status?.fields ?? {})
    .filter(([, value]) => value?.status !== "recorded")
    .map(([key]) => metricLabel(key, language));
  return (
    <article className="long-term-summary__technical-model">
      <div className="story-card__header">
        <strong>{modelTaskLabel(entry.task, language)}</strong>
        <span className="tag">{entry.status ?? "research_only"}</span>
      </div>
      <p className="muted">
        {language === "zh-CN" ? "结构" : "Architecture"}: {entry.architecture ?? "—"} · {language === "zh-CN" ? "版本" : "Version"}: {entry.model_version ?? "—"}
        · {language === "zh-CN" ? "窗口" : "Window"}: {entry.window_sessions ?? "—"} {language === "zh-CN" ? "个交易日" : "sessions"}
      </p>
      <p className="muted">
        {language === "zh-CN" ? "训练样本" : "Training sample"}: {entry.training_symbol_count ?? "—"} {language === "zh-CN" ? "只标的" : "symbols"} / {entry.training_date_count ?? "—"} {language === "zh-CN" ? "个日期" : "dates"}
        · {language === "zh-CN" ? "特征数" : "Features"}: {entry.feature_count ?? "—"}
      </p>
      <p className="muted">
        {language === "zh-CN" ? "训练区间" : "Training range"}: {dateRangeLabel(entry.training_date_range, language)}
      </p>
      <p className="muted">
        {language === "zh-CN" ? "留出指标" : "Holdout metrics"}: {metrics.length
          ? metrics.map(([key, value]) => `${metricLabel(key, language)} ${formatTechnicalMetric(key, value, language)}`).join(" · ")
          : "—"}
      </p>
      <p className="muted">
        {language === "zh-CN" ? "指标覆盖" : "Metric coverage"}: {entry.evaluation_metric_status?.recorded_count ?? 0}/{entry.evaluation_metric_status?.required_count ?? 0}
        {entry.evaluation_metric_status?.missing_count ? (language === "zh-CN" ? `（${entry.evaluation_metric_status.missing_count} 项未记录）` : ` (${entry.evaluation_metric_status.missing_count} not recorded)`) : ""}
      </p>
      {missingMetrics.length ? <p className="muted">{language === "zh-CN" ? "未记录字段" : "Not recorded"}: {missingMetrics.join(language === "zh-CN" ? "、" : ", ")}</p> : null}
      <p className="muted">
        {language === "zh-CN" ? "PIT / 快照" : "PIT / snapshot"}: {entry.data_tier ?? "—"} · {shortHash(entry.snapshot_id)} · {shortHash(entry.snapshot_hash)}
        · {language === "zh-CN" ? "数据集哈希" : "Dataset hash"}: {shortHash(entry.dataset_hash)}
      </p>
      <p className="muted">
        {language === "zh-CN" ? "模型哈希" : "Model hash"}: {shortHash(entry.model_hash)} · {language === "zh-CN" ? "评估哈希" : "Report hash"}: {shortHash(entry.report_hash)} · {language === "zh-CN" ? "Fold 哈希" : "Fold hash"}: {shortHash(entry.fold_hash)}
      </p>
      <p className="muted">
        {language === "zh-CN" ? "Provider" : "Provider"}: {entry.provider ?? (language === "zh-CN" ? "评估文件未记录" : "Not recorded in evaluation")}
        · Shadow: {entry.shadow_status ?? (language === "zh-CN" ? "等待独立验证" : "Awaiting independent validation")}
      </p>
      <p className="muted">
        {language === "zh-CN" ? "换手 / 容量" : "Turnover / capacity"}: {entry.turnover == null ? "—" : formatTechnicalMetric("turnover", entry.turnover)} · {entry.capacity_estimate == null ? (language === "zh-CN" ? "尚未估计（缺少成交额冲击模型）" : "Not estimated (no volume-impact model)") : formatTechnicalMetric("capacity", entry.capacity_estimate)}
      </p>
    </article>
  );
}

function CandidateEntry({ entry, language }: { entry: LongTermModelCandidate; language: "zh-CN" | "en-US" }) {
  const metrics = entry.holdout_metrics ?? {};
  const rankKey = metrics.rank_ic != null ? "rank_ic" : metrics.risk_rank_ic != null ? "risk_rank_ic" : null;
  return (
    <p className="muted long-term-summary__candidate">
      {modelTaskLabel(entry.task, language)} · {entry.architecture ?? "—"} / {entry.variant ?? (language === "zh-CN" ? "默认变体" : "default variant")}
      · {entry.is_primary ? (language === "zh-CN" ? "主模型" : "primary") : (language === "zh-CN" ? "候选" : "candidate")}
      · {language === "zh-CN" ? "训练区间" : "Training range"}: {dateRangeLabel(entry.training_date_range, language)}
      · {language === "zh-CN" ? "指标" : "Metrics"}: {entry.evaluation_metric_status?.recorded_count ?? 0}/{entry.evaluation_metric_status?.required_count ?? 0}
      · {rankKey ? `${metricLabel(rankKey, language)} ${formatTechnicalMetric(rankKey, metrics[rankKey] as number, language)}` : (language === "zh-CN" ? "无排序指标" : "no rank metric")}
      · {language === "zh-CN" ? "评估引用" : "evaluation ref"}: {entry.evaluation_ref ?? "—"}
    </p>
  );
}

/** A plain-language evidence summary; it deliberately does not manufacture a long-term score. */
export function LongTermInvestorSummary({ forecast, acceptance, scorecard, language }: Props) {
  const zh = language === "zh-CN";
  const coverage = forecast?.data_status.coverage_ratio ?? acceptance?.data?.market_coverage?.[0]?.coverage_ratio;
  const eventStatus = forecast?.data_status.event_coverage_status ?? acceptance?.data?.market_coverage?.[0]?.event_coverage_status;
  const evidence = forecast?.evidence_status ?? acceptance?.evidence_status ?? "missing";
  const card = scorecard?.scorecard;
  const modelReadings = scorecard?.long_term_model_readings ?? card?.long_term_model_readings ?? {};
  const requiredModelTasks = ["excess_return_120d", "excess_return_240d", "future_max_drawdown_120d", "future_max_drawdown_240d"];
  const modelReadingsComplete = requiredModelTasks.every((task) => {
    const reading = modelReadings[task];
    return reading && reading.q10 != null && reading.q50 != null && reading.q90 != null;
  });
  const modelRegistry = scorecard?.long_term_model_registry;
  const score = (value: number | null | undefined) => value == null ? (zh ? "待补齐" : "To be added") : `${Math.round(value)}/100`;
  const blocked = scorecard?.status === "blocked"
    || acceptance?.status === "blocked"
    || evidence === "missing"
    || evidence === "blocked"
    || forecast?.prediction_status === "blocked"
    || (scorecard?.status === "available" && !modelReadingsComplete)
    || (!forecast && !acceptance && scorecard?.status !== "available");

  return (
    <article className="story-card long-term-summary" data-testid="long-term-investor-summary">
      <div className="story-card__header">
        <strong>{zh ? "给长期投资者的一分钟摘要" : "One-minute summary for long-term investors"}</strong>
        <span className={`tag ${blocked ? "tag--warn" : ""}`}>{blocked ? (zh ? "证据不足" : "Evidence limited") : (zh ? "研究中" : "Research only")}</span>
      </div>
      <p className="long-term-summary__lead">
        {zh
          ? "长期模型同时观察 120/240 日相对表现和潜在回撤；1 日、5 日或 20 日读数只用于近期市场观察。"
          : "Long-term models cover 120/240-day relative performance and potential drawdown; 1/5/20-day readings remain near-term market observations."}
      </p>
      <div className="long-term-summary__grid">
        <div><span>{zh ? "经营质量" : "Business quality"}</span><strong>{score(card?.long_term_quality)}</strong></div>
        <div><span>{zh ? "成长稳定性" : "Growth stability"}</span><strong>{score(card?.growth_stability)}</strong></div>
        <div><span>{zh ? "估值位置" : "Valuation position"}</span><strong>{score(card?.valuation_position)}</strong></div>
        <div><span>{zh ? "股东回报" : "Shareholder return"}</span><strong>{score(card?.shareholder_return)}</strong></div>
        <div><span>{zh ? "主要风险" : "Main risks"}</span><strong>{score(card?.long_term_risk)}</strong></div>
        <div><span>{zh ? "相对表现（约6个月）" : "Relative performance (6m)"}</span><strong>{modelRange(modelReadings.excess_return_120d, language)}</strong></div>
        <div><span>{zh ? "相对表现（约12个月）" : "Relative performance (12m)"}</span><strong>{modelRange(modelReadings.excess_return_240d, language)}</strong></div>
        <div><span>{zh ? "潜在回撤（约6个月）" : "Potential drawdown (6m)"}</span><strong>{modelRange(modelReadings.future_max_drawdown_120d, language)}</strong></div>
        <div><span>{zh ? "潜在回撤（约12个月）" : "Potential drawdown (12m)"}</span><strong>{modelRange(modelReadings.future_max_drawdown_240d, language)}</strong></div>
        <div><span>{zh ? "组合影响" : "Portfolio impact"}</span><strong>{zh ? "尚未配置组合" : "No portfolio configured"}</strong></div>
        <div><span>{zh ? "数据覆盖" : "Data coverage"}</span><strong>{pct(coverage)}</strong></div>
        <div><span>{zh ? "事件覆盖" : "Event coverage"}</span><strong>{eventStatus ? (zh ? eventStatus === "complete" ? "完整" : eventStatus === "partial" ? "部分" : "缺失" : eventStatus) : "—"}</strong></div>
        <div><span>{zh ? "数据新鲜度" : "Data freshness"}</span><strong>{forecast?.data_status.cache_state ? (zh ? forecast.data_status.cache_state === "fresh" ? "较新" : "需复核" : forecast.data_status.cache_state) : "—"}</strong></div>
        <div><span>{zh ? "证据完整度" : "Evidence completeness"}</span><strong>{card?.evidence_completeness != null ? score(card.evidence_completeness) : evidence === "valid" ? (zh ? "较完整" : "Mostly complete") : (zh ? "不完整" : "Incomplete")}</strong></div>
        <div><span>{zh ? "当前可说什么" : "What we can say"}</span><strong>{blocked ? (scorecard?.status === "available" && !modelReadingsComplete ? (zh ? "等待模型读数" : "Model readings pending") : (zh ? "先补数据" : "Fix data first")) : (zh ? "四项模型观察" : "Four model readings")}</strong></div>
      </div>
      <div className="long-term-summary__explain">
        <div>
          <span>{zh ? "最近发生了什么" : "What happened"}</span>
          <p>{forecast?.data_status.as_of ? (zh ? `数据截至 ${forecast.data_status.as_of}；长期模型读数按各自适用期限展示。` : `Data is as of ${forecast.data_status.as_of}; long-term model readings are shown with their applicable horizons.`) : (zh ? "还没有可引用的冻结时间点。" : "No frozen as-of time is available yet.")}</p>
        </div>
        <div>
          <span>{zh ? "支持与反方证据" : "Evidence for / against"}</span>
          <p>{zh ? `支持：行情覆盖 ${pct(coverage)}、事件状态 ${eventStatus ?? "未知"}${modelReadingsComplete ? "，并同时提供四个长期模型读数" : "；四个长期模型读数尚待生成"}。反方：财报、估值和模型区间仍需结合后续披露继续观察。` : `For: ${pct(coverage)} market coverage and event status ${eventStatus ?? "unknown"}${modelReadingsComplete ? ", with four long-term model readings" : "; four long-term model readings are still pending"}. Against: fundamentals, valuation and model intervals should be reviewed as new disclosures arrive.`}</p>
        </div>
        <div>
          <span>{zh ? "接下来观察什么" : "What to watch next"}</span>
          <p>{zh ? "观察下一次公告后的盈利质量、行业相对表现、融资变化和回撤；若数据修订或事件覆盖下降，应撤回当前判断。" : "Watch post-announcement earnings quality, industry relative performance, financing changes and drawdown; withdraw the view if revisions or event coverage deteriorate."}</p>
        </div>
        <div>
          <span>{zh ? "什么会推翻当前判断" : "What could overturn this view"}</span>
          <p>{zh ? "新的公告、财报修订、行业归属变化或更完整的反方证据，可能使当前观察失效；在这些证据出现前不应把研究参考当成确定结论。" : "New announcements, financial revisions, industry changes or stronger contrary evidence may invalidate this view; until then, treat it as a research reference rather than a certainty."}</p>
        </div>
      </div>
      <details className="long-term-summary__technical" data-testid="long-term-professional-details">
        <summary>{zh ? "专业详情（默认折叠）" : "Professional details (collapsed by default)"}</summary>
        <p className="muted">
          {zh
            ? "这里保留四个模型的训练范围、PIT 快照、评估摘要和引用哈希，供 Pre 与专业用户核对；这些信息不等同于交易结论。"
            : "This section keeps the four models' training scope, PIT snapshot, evaluation summary and citation hashes for Pre and technical review; it is not a trading conclusion."}
        </p>
        {(modelRegistry?.models ?? []).map((entry) => <RegistryEntry key={entry.task} entry={entry} language={language} />)}
        {!modelRegistry?.models?.length ? <p className="muted">{zh ? "模型训练详情尚未生成，等待评估文件补齐。" : "Training details are not available yet; waiting for evaluation artifacts."}</p> : null}
        <details className="long-term-summary__technical-candidates">
          <summary>{zh ? `候选模型训练记录（${modelRegistry?.candidate_count ?? 0} 个）` : `Candidate training records (${modelRegistry?.candidate_count ?? 0})`}</summary>
          <p className="muted">{zh ? `候选结构：${(modelRegistry?.candidate_architectures ?? []).join("、") || "—"}` : `Candidate architectures: ${(modelRegistry?.candidate_architectures ?? []).join(", ") || "—"}`}</p>
          {(modelRegistry?.candidate_models ?? []).map((entry, index) => <CandidateEntry key={`${entry.evaluation_ref ?? entry.task}-${index}`} entry={entry} language={language} />)}
        </details>
        <p className="muted">
          {zh ? "注册表引用" : "Registry reference"}: {modelRegistry?.source_ref ?? "—"} · {zh ? "清单哈希" : "Manifest hash"}: {shortHash(modelRegistry?.source_hash)}
          · {zh ? "读数文件" : "Readings artifact"}: {scorecard?.model_readings_source_ref ?? (zh ? "尚未生成" : "Not generated yet")}
        </p>
        <p className="muted">
          {zh ? "研究产物注册" : "Research artifact registration"}: {modelRegistry?.artifact_registration_ref ?? (zh ? "尚未生成" : "Not generated yet")}
          · {zh ? "状态" : "Status"}: {modelRegistry?.artifact_registration_status ?? "—"}
          · {zh ? "注册清单哈希" : "Registration hash"}: {shortHash(modelRegistry?.artifact_registration_hash)}
        </p>
      </details>
      <p className="muted long-term-summary__next">
        {zh ? "下一步：补齐 PIT 财报、融资、宏观和市场宽度；通过快照门禁后，先评估 5/20 日辅助排序，再评估季度级 120/240 日 Rank IC、扣费后 Top-K 和回撤。" : "Next: complete PIT fundamentals, financing, macro and breadth data; then evaluate 5/20-day auxiliary ranking and quarterly 120/240-day Rank IC, cost-adjusted Top-K and drawdown behind the snapshot gate."}
      </p>
    </article>
  );
}
