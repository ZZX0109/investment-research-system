import React from "react";
import { LogOut, Search, ShieldCheck } from "lucide-react";
import ApiKeyPanel from "../../components/ApiKeyPanel";
import SourceMetaBadge from "../../components/SourceMetaBadge";
import type { Holding, PortfolioPayload, PreferenceKey, RefreshReviewPayload, ResearchPayload, UserProfile, UserProfileState, ApiKeySummary } from "../../components/types";
import { formatDateTime } from "../../components/utils";
import { preferenceOptions } from "../../preferences";
import FailureStrategyPanel from "./FailureStrategyPanel";
import AuditStep from "./steps/AuditStep";
import EvidenceStep from "./steps/EvidenceStep";
import HoldingsStep from "./steps/HoldingsStep";
import RiskStep from "./steps/RiskStep";
import type { Step } from "./types";
import { STEPS } from "./types";

interface WorkbenchPageProps {
  apiKeys: ApiKeySummary[];
  apiState: "loading" | "live" | "fallback";
  currentStep: Step;
  error: string | null;
  portfolio: PortfolioPayload;
  preference: PreferenceKey;
  profile: UserProfileState;
  refreshReview: RefreshReviewPayload | null;
  research: ResearchPayload;
  selectedSymbol: string;
  token: string;
  uploadState: string;
  user: UserProfile;
  onApiKeyChange: () => Promise<void>;
  onCurrentStepChange: (step: Step) => void;
  onDocumentUpload: (file: File | null) => void;
  onLogout: () => void;
  onPreferenceChange: (preference: PreferenceKey) => void;
  onRefreshDaily: () => void;
  onReportFrequencyChange: (frequency: string) => void;
  onSelectedSymbolChange: (symbol: string) => void;
}

export default function WorkbenchPage({
  apiKeys,
  apiState,
  currentStep,
  error,
  portfolio,
  preference,
  profile,
  refreshReview,
  research,
  selectedSymbol,
  token,
  uploadState,
  user,
  onApiKeyChange,
  onCurrentStepChange,
  onDocumentUpload,
  onLogout,
  onPreferenceChange,
  onRefreshDaily,
  onReportFrequencyChange,
  onSelectedSymbolChange,
}: WorkbenchPageProps) {
  const selectedHolding: Holding = portfolio.holdings.find((item) => item.symbol === selectedSymbol) ?? portfolio.holdings[0];

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="产品导航">
        <div className="brand">
          <span className="brand-mark">IA</span>
          <div>
            <strong>Investment Agent Workflow</strong>
            <span>真实闭环投研</span>
          </div>
        </div>

        <nav className="step-nav">
          {STEPS.map((step) => (
            <button className={`step-nav-item ${currentStep === step.key ? "active" : ""}`} key={step.key} onClick={() => onCurrentStepChange(step.key)} type="button">
              {step.icon}
              <span>{step.label}</span>
            </button>
          ))}
        </nav>

        <div className="account-box">
          <strong>{user.email}</strong>
          <span>{profile.onboardingCompleted ? "已完成前测" : "待前测"}</span>
          <button onClick={onLogout}>
            <LogOut size={15} />
            退出登录
          </button>
        </div>
        <div className="side-note">
          <ShieldCheck size={18} />
          <span>仅供研究学习，不构成投资建议。模型推断必须绑定证据与时间。</span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">账户持仓驱动 · 真实数据优先 · 证据过期归档</p>
            <h1>组合风险与 Agent 投研闭环</h1>
          </div>
          <label className="search-box">
            <Search size={18} />
            <input value={selectedSymbol} onChange={(event) => onSelectedSymbolChange(event.target.value.toUpperCase())} aria-label="搜索股票代码" />
          </label>
        </header>

        <section className="status-strip">
          <span className={`status-dot ${apiState}`} />
          <strong>{apiState === "live" ? "后端 API 已连接" : apiState === "loading" ? "正在连接后端 API" : "数据源不可用/部分兜底"}</strong>
          <span>{portfolio.cacheStatus.label}</span>
          <span>更新时间: {formatDateTime(portfolio.cacheStatus.asOf)}</span>
          {selectedHolding ? <span>当前标的源: {selectedHolding.dataSource ?? "local cache"} · {selectedHolding.dataStatus ?? "unknown"}</span> : null}
          <SourceMetaBadge meta={portfolio.sourceMeta} compact />
          {error ? <span className="status-error">{error}</span> : null}
        </section>

        {research.qualityGate ? (
          <section className="panel gate-panel">
            <div className="panel-head">
              <div>
                <h2>Judge 质量门禁</h2>
                <p>{research.qualityGate.summary}</p>
              </div>
              <span className={`risk-badge ${research.qualityGate.status === "BLOCK" ? "high" : research.qualityGate.status === "HOLD" ? "medium" : "low"}`}>
                {research.qualityGate.status}
              </span>
            </div>
            <SourceMetaBadge meta={research.sourceMeta} />
          </section>
        ) : null}

        <FailureStrategyPanel apiState={apiState} error={error} portfolio={portfolio} research={research} onRefresh={onRefreshDaily} />

        <section className="preference-panel">
          <div>
            <h2>用户前测与二次偏好</h2>
            <p>{portfolio.preference.description}</p>
          </div>
          <div className="segmented-control" aria-label="用户偏好">
            {preferenceOptions.map((option) => (
              <button className={option.key === preference ? "selected" : ""} key={option.key} onClick={() => onPreferenceChange(option.key)} title={option.description}>
                {option.label}
              </button>
            ))}
          </div>
        </section>

        <ApiKeyPanel apiKeys={apiKeys} token={token} onChange={onApiKeyChange} compact />

        <section className="workflow-strip">
          {research.agentWorkflow.map((step, index) => (
            <article className="workflow-step" key={step.role} title={step.output}>
              <span>{index + 1}</span>
              <div>
                <strong>{step.role}</strong>
                <small>{step.kind} · {step.status}</small>
                <p>{step.output}</p>
              </div>
            </article>
          ))}
        </section>

        {currentStep === "holdings" ? <HoldingsStep portfolio={portfolio} research={research} selectedHolding={selectedHolding} onSelectSymbol={onSelectedSymbolChange} /> : null}
        {currentStep === "risk" ? <RiskStep research={research} uploadState={uploadState} onDocumentUpload={onDocumentUpload} onReportFrequencyChange={onReportFrequencyChange} /> : null}
        {currentStep === "evidence" ? <EvidenceStep research={research} /> : null}
        {currentStep === "audit" ? <AuditStep research={research} refreshReview={refreshReview} token={token} onRefreshDaily={onRefreshDaily} /> : null}
      </section>
    </main>
  );
}
