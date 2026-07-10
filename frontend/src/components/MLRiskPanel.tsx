import React from "react";
import { Database, Radar } from "lucide-react";
import type { ResearchPayload } from "./types";
import { ratioPercent } from "./utils";

interface MLRiskPanelProps {
  research: ResearchPayload;
}

export default function MLRiskPanel({ research }: MLRiskPanelProps) {
  const ml = research.mlRiskSummary;
  const scenarios = ml?.similarScenarios ?? [];
  return (
    <div className="ml-risk-panel">
      <article className="document-block">
        <h3>
          <Database size={18} />
          模型状态
        </h3>
        <p>{ml?.summary ?? "尚未生成模型推断。Research Quality Judge 会将时序模型结论标记为缺失。"}</p>
        <div className="ml-status-row">
          <span>model: {ml?.modelId ?? "none"}</span>
          <span>type: {ml?.modelType ?? "none"}</span>
          <span>asOf: {ml?.asOfDate ?? "N/A"}</span>
          <span>calibration: {ml?.calibrationStatus ?? "missing"}</span>
        </div>
      </article>
      <div className="metric-table ml-metric-table">
        <div>
          <span>风险状态</span>
          <strong>{ml?.riskRegime ?? "missing"}</strong>
          <small>{ml?.market ?? research.market} · {ml?.symbol ?? research.symbol}</small>
        </div>
        <div>
          <span>1 月 P90 回撤</span>
          <strong>{ratioPercent(ml?.drawdownP90_1m)}</strong>
          <small>1周 P90 {ratioPercent(ml?.riskDistribution?.drawdownQuantiles1w?.p90)} · P95 {ratioPercent(ml?.drawdownP95_1m)}</small>
        </div>
        <div>
          <span>1 月波动率</span>
          <strong>{ratioPercent(ml?.volatilityP90_1m ?? ml?.volatilityP50_1m)}</strong>
          <small>P50 {ratioPercent(ml?.volatilityP50_1m)} · confidence {ratioPercent(ml?.confidence)}</small>
        </div>
        <div>
          <span>VaR breach</span>
          <strong>{ratioPercent(ml?.varBreachProbability)}</strong>
          <small>threshold {ratioPercent(ml?.varThreshold)} · highRisk {ml?.highRiskRegime ? "yes" : "no"}</small>
        </div>
        <div>
          <span>PIT 字段检查</span>
          <strong>{ml?.featureStoreAudit?.ok ? "pass" : "fail"}</strong>
          <small>{ml?.featureStoreAudit?.checkedFieldCount ?? 0} fields · future {ml?.featureStoreAudit?.futureLeakageCount ?? 0}</small>
        </div>
        <div>
          <span>校准/回测</span>
          <strong>{ml?.validationMetrics?.calibration_ece !== undefined ? String(ml.validationMetrics.calibration_ece) : "missing"}</strong>
          <small>ECE · pinball {ml?.validationMetrics?.pinball_loss !== undefined ? String(ml.validationMetrics.pinball_loss) : "missing"}</small>
        </div>
      </div>
      <article className="document-block">
        <h3>
          <Radar size={18} />
          相似历史情景
        </h3>
        {scenarios.length ? (
          <div className="scenario-table-wrap">
            <table className="scenario-table">
              <thead>
                <tr>
                  <th>标的 / 日期</th>
                  <th>相似度</th>
                  <th>1周</th>
                  <th>1月</th>
                  <th>3月</th>
                  <th>1周最大回撤</th>
                  <th>1月最大回撤</th>
                </tr>
              </thead>
              <tbody>
                {scenarios.slice(0, 5).map((scenario) => (
                  <tr key={`${scenario.matchedSymbol}-${scenario.matchedAsOfDate}-${scenario.modelId}`}>
                    <td>{scenario.matchedSymbol} · {scenario.matchedAsOfDate}</td>
                    <td>{(scenario.similarity * 100).toFixed(1)}%</td>
                    <td>{ratioPercent(scenario.return1w)}</td>
                    <td>{ratioPercent(scenario.return1m)}</td>
                    <td>{ratioPercent(scenario.return3m)}</td>
                    <td>{ratioPercent(scenario.maxDrawdown1w)}</td>
                    <td>{ratioPercent(scenario.maxDrawdown1m)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-text">暂无相似情景。需要先构建特征快照并完成模型推理。</p>
        )}
      </article>
    </div>
  );
}
