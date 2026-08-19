import { Panel } from "../../components/Panel";
import { useI18n } from "../../i18n";
import { useLatestLongTermScorecardQuery, useResearchForecastQuery, useResearchShadowSummaryQuery } from "../../hooks/useWorkbenchQueries";
import { LongTermInvestorSummary } from "./LongTermInvestorSummary";
import { useResearchWorkspace } from "./useResearchWorkspace";

/** Compact center-column research view; technical material stays in one drawer. */
export function ResearchPanel() {
  const { l, language } = useI18n();
  const workspace = useResearchWorkspace();
  const scorecard = useLatestLongTermScorecardQuery(workspace.assetTicker);
  const forecast = useResearchForecastQuery(workspace.selectedRunId);
  const shadow = useResearchShadowSummaryQuery(workspace.assetTicker);

  return (
    <Panel eyebrow={l("长期研究", "Long-term research")} title={l("长期投资分析", "Long-term investment analysis")}>
      {workspace.assetId ? (
        <>
          <LongTermInvestorSummary forecast={forecast.data} acceptance={undefined} scorecard={scorecard.data} language={language} />
          <details className="research-supporting-details" data-testid="research-supporting-details">
            <summary>
              <span>{l("更多研究证据和运行详情", "More research evidence and run details")}</span>
              <small>{l("只保留模型任务、历史验证和引用信息，专业内容默认折叠", "Model tasks, forward validation and references; professional content stays collapsed")}</small>
            </summary>
            <article className="story-card research-compact-details">
              <div className="metric-strip">
                <div className="metric-card"><div className="eyebrow">{l("长期模型", "Long-term models")}</div><div className="metric-card__value">{Object.keys(scorecard.data?.long_term_model_readings ?? {}).length || "—"}</div></div>
                <div className="metric-card"><div className="eyebrow">{l("研究任务", "Research tasks")}</div><div className="metric-card__value">{forecast.data?.tasks.length ?? "—"}</div></div>
                <div className="metric-card"><div className="eyebrow">{l("前向记录", "Forward records")}</div><div className="metric-card__value">{shadow.data?.valid_session_count ?? "—"}</div></div>
                <div className="metric-card"><div className="eyebrow">{l("数据日期", "Data date")}</div><div className="metric-card__value">{forecast.data?.data_status.as_of?.slice(0, 10) ?? scorecard.data?.scorecard?.as_of_date ?? "—"}</div></div>
              </div>
              {forecast.data?.influence_facts.length ? <p className="muted">{l("模型关注因素", "Model focus")}: {forecast.data.influence_facts.join("；")}</p> : null}
              <p className="muted">{l("模型读数用于解释经营质量、成长、估值、股东回报和风险变化；实际判断仍应结合后续公告、财报和行业变化。", "Model readings explain changes in business quality, growth, valuation, shareholder return and risk; review later disclosures, financials and industry changes before drawing conclusions.")}</p>
            </article>
          </details>
        </>
      ) : <p className="muted">{l("请选择研究对象，以查看长期投资分析。", "Select an asset to view the long-term investment analysis.")}</p>}
    </Panel>
  );
}
