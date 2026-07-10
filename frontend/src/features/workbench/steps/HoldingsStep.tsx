import React from "react";
import { BarChart3, CircleDollarSign, LineChart, Newspaper, Radar, TrendingUp } from "lucide-react";
import AnalogyTable from "../../../components/AnalogyTable";
import HoldingButton from "../../../components/HoldingButton";
import LineChartSvg from "../../../components/LineChartSvg";
import MetricCard from "../../../components/MetricCard";
import MiniPriceChart from "../../../components/MiniPriceChart";
import RadarBars from "../../../components/RadarBars";
import SourceMetaBadge from "../../../components/SourceMetaBadge";
import type { Holding, PortfolioPayload, ResearchPayload } from "../../../components/types";
import { currency, metricClass, percent } from "../../../components/utils";

interface HoldingsStepProps {
  portfolio: PortfolioPayload;
  research: ResearchPayload;
  selectedHolding: Holding;
  onSelectSymbol: (symbol: string) => void;
}

export default function HoldingsStep({ portfolio, research, selectedHolding, onSelectSymbol }: HoldingsStepProps) {
  return (
    <div className="step-content">
      <section className="metric-grid">
        <MetricCard icon={<CircleDollarSign size={20} />} label="组合市值" value={currency.format(portfolio.metrics.marketValue)} detail={`${portfolio.holdings.length} 个持仓/观察标的`} />
        <MetricCard icon={<TrendingUp size={20} />} label="累计收益" value={percent(portfolio.metrics.totalReturn)} detail={`成本 ${currency.format(portfolio.metrics.cost)}`} tone={metricClass(portfolio.metrics.totalReturn)} />
        <MetricCard icon={<BarChart3 size={20} />} label="今日盈亏" value={currency.format(portfolio.metrics.todayPnl)} detail="按持仓权重估算" tone={metricClass(portfolio.metrics.todayPnl)} />
        <MetricCard icon={<Radar size={20} />} label="最大单项权重" value={`${portfolio.metrics.topWeight.toFixed(1)}%`} detail="集中度需持续观察" tone="warn" />
      </section>

      <section className="main-grid">
        <section className="panel wide">
          <div className="panel-head">
            <div>
              <h2>组合收益曲线</h2>
              <p>结构化行情入库；当前曲线来源: {portfolio.portfolioCurveSource}。</p>
            </div>
            <SourceMetaBadge meta={portfolio.sourceMeta} compact />
          </div>
          <LineChartSvg points={portfolio.portfolioCurve} />
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>组合风险雷达</h2>
              <p>偏好会改变风险权重，但不生成确定性买卖指令。</p>
            </div>
          </div>
          <RadarBars items={portfolio.riskRadar} />
        </section>

        <section className="panel holdings-panel">
          <div className="panel-head">
            <div>
              <h2>用户持仓列表</h2>
              <p>点击标的触发行情、证据链和历史情景刷新。</p>
            </div>
          </div>
          <div className="holding-list">
            {portfolio.holdings.map((holding) => (
              <HoldingButton holding={holding} selected={holding.symbol === selectedHolding.symbol} key={holding.symbol} onClick={() => onSelectSymbol(holding.symbol)} />
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>巡检设置</h2>
              <p>观察池会检查证据有效期，旧证据进入经验历史池。</p>
            </div>
          </div>
          <div className="event-list">
            {portfolio.events.map((event) => (
              <article className="event-item" key={event.title}>
                <span className={`event-dot ${event.tone}`} />
                <div>
                  <strong>{event.title}</strong>
                  <p>{event.summary}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="panel research-panel wide">
          <div className="panel-head">
            <div>
              <h2>{research.symbol} 多模态投研卡片</h2>
              <p>{research.name} · 文档解释、证据表格、价格图表和历史情景合并展示。</p>
            </div>
            <span className={`risk-badge ${research.riskLevel}`}>{research.riskLabel}</span>
          </div>
          <div className="research-layout">
            <div className="document-column">
              {research.documentBlocks.map((block) => (
                <article className="document-block" key={block.title}>
                  <h3><Newspaper size={18} />{block.title}</h3>
                  <p>{block.text}</p>
                </article>
              ))}
            </div>
            <div className="mini-chart-card">
              <h3><LineChart size={18} />近阶段价格路径</h3>
              <MiniPriceChart points={research.priceSeries.map((item) => item.close)} />
              <div className="source-meta-list">
                <SourceMetaBadge meta={research.priceSeries[0]?.sourceMeta} compact />
              </div>
            </div>
          </div>
        </section>

        <section className="panel wide">
          <div className="panel-head">
            <div>
              <h2>过去三年相似情景预览</h2>
              <p>完整证据链页面会展开所有类比来源和非预测说明。</p>
            </div>
          </div>
          <AnalogyTable analogies={research.historicalAnalogies.slice(0, 2)} />
        </section>
      </section>
    </div>
  );
}
