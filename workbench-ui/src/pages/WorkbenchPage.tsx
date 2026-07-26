import { ModeSwitch } from "../components/ModeSwitch";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { useI18n } from "../i18n";
import { Activity, Clock3, Database, Globe2, KeyRound, LockKeyhole, ShieldCheck } from "lucide-react";
import { AnalysisPanel } from "../features/analysis/AnalysisPanel";
import { ResearchAuditPanel } from "../features/audit/ResearchAuditPanel";
import { AuthCard } from "../features/auth/AuthCard";
import { AuditPanel } from "../features/governance/AuditPanel";
import { ProvenancePanel } from "../features/governance/ProvenancePanel";
import { RunLineagePanel } from "../features/governance/RunLineagePanel";
import { TechnicalAuditHub } from "../features/governance/TechnicalAuditHub";
import { SelectedRunContextBar } from "../features/governance/SelectedRunContextBar";
import { PortfolioPanel } from "../features/overview/PortfolioPanel";
import { ResearchPanel } from "../features/research/ResearchPanel";
import { ResearchUserSidebar } from "../features/research/ResearchUserSidebar";
import { HistoricalAnalogyPanel } from "../features/history/HistoricalAnalogyPanel";
import { ResearchOperationsPanel } from "../features/operations/ResearchOperationsPanel";
import { PortfolioRiskPanel } from "../features/risk/PortfolioRiskPanel";
import { useWorkbenchStore } from "../state/workbenchStore";
import { AgentExecutionPanel } from "../features/agent/AgentExecutionPanel";
import { useConfigureLLMProviderMutation, useLLMCredentialsQuery, useLLMProviderProfilesQuery } from "../hooks/useWorkbenchQueries";
import { useState } from "react";

export function WorkbenchPage() {
  const mode = useWorkbenchStore((state) => state.mode);
  const selectedRunId = useWorkbenchStore((state) => state.selectedRunId);
  const setMode = useWorkbenchStore((state) => state.setMode);
  const { l, t } = useI18n();
  return (
    <div className="workbench-shell">
      <header className="app-header">
        <div className="brand-lockup">
          <Activity size={22} aria-hidden="true" />
          <div><h1>{t("brand.name")}</h1><span>{t("brand.tagline")}</span></div>
        </div>
        <div className="app-header__context" aria-label={t("header.context")}>
          <span><Globe2 size={14} /> {t("header.market")}</span>
          <span><Clock3 size={14} /> {t("header.closeConfirmed")}</span>
        </div>
        <div className="app-header__status">
          {mode === "research" ? (
            <span className="system-status"><Database size={15} aria-hidden="true" /> {l("免费公开数据", "Free public data")}</span>
          ) : (
            <>
              <span className="system-status"><Database size={15} aria-hidden="true" /> {mode} {l("数据", "data")}</span>
              <span className="system-status"><ShieldCheck size={15} aria-hidden="true" /> {t("header.strictGate")}</span>
              <span className={`system-status ${mode === "real" ? "system-status--blocked" : ""}`}><LockKeyhole size={14} /> {mode === "real" ? l("正式授权：已阻断", "Formal access: blocked") : l("正式授权：未启用", "Formal access: not enabled")}</span>
            </>
          )}
          <LanguageSwitch />
          <LLMApiKeyButton />
          <ModeSwitch mode={mode} onChange={setMode} />
        </div>
      </header>

      {mode === "research" ? (
        <div className="research-mode-banner" role="status">
          {t("banner.research")}
        </div>
      ) : mode === "real" ? (
        <div className="research-mode-banner research-mode-banner--formal" role="status">
          {t("banner.formal")}
        </div>
      ) : null}

      {mode !== "research" ? <SelectedRunContextBar /> : null}

      {mode === "research" ? (
        <>
          <main className="workspace-grid workspace-grid--research">
            <div className="workspace-column workspace-column--research-nav">
              <div className="research-sidebar-auth"><AuthCard /></div>
              <PortfolioPanel />
            </div>
            <div className="workspace-column workspace-column--wide">
              <AgentExecutionPanel />
              <HistoricalAnalogyPanel />
            </div>
            <div className="workspace-column">
              <ResearchUserSidebar />
            </div>
          </main>
          <details className="technical-drawer">
            <summary>
              <span>{l("技术与审计详情", "Technical and audit details")}</span>
              <small>{l("供模型研究、数据核验和历史回放使用，普通使用无需查看", "For model research, data verification and historical replay; not required for normal use")}</small>
            </summary>
            <TechnicalAuditHub />
          </details>
        </>
      ) : (
        <main className="workspace-grid">
          <div className="workspace-column">
            <AuthCard />
            <PortfolioPanel />
          </div>
          <div className="workspace-column workspace-column--wide">
            <AgentExecutionPanel />
            <AnalysisPanel />
            <HistoricalAnalogyPanel />
            <ResearchPanel />
          </div>
          <div className="workspace-column">
            <PortfolioRiskPanel />
            <details className="governance-accordion" open={Boolean(selectedRunId)}>
              <summary>
                <span>{l("数据与治理", "Data and governance")}</span>
                <small>{l("证据、来源、运行和审计状态", "Evidence, provenance, operations and audit")}</small>
              </summary>
              <div className="governance-accordion__body">
                <ResearchAuditPanel />
                <ResearchOperationsPanel />
                <ProvenancePanel />
                <RunLineagePanel />
                <AuditPanel />
              </div>
            </details>
          </div>
        </main>
      )}
    </div>
  );
}

function LLMApiKeyButton() {
  const { l } = useI18n();
  const isPublicDemo = import.meta.env.VITE_PUBLIC_DEMO === "true";
  const mode = useWorkbenchStore((state) => state.mode);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ name: "研究助手", endpoint: "https://api.openai.com/v1/chat/completions", model: "gpt-4o-mini", credentialId: "research-openai", secret: "" });
  const profiles = useLLMProviderProfilesQuery();
  const credentials = useLLMCredentialsQuery();
  const configure = useConfigureLLMProviderMutation();
  const activeProfile = profiles.data?.find((profile) => profile.enabled);

  if (isPublicDemo) {
    return <span className="system-status" title={l("公网演示版不会收集或保存访问者的 API Key", "The public demo does not collect or store visitor API keys")}><LockKeyhole size={14} aria-hidden="true" /> {l("只读演示", "Read-only demo")}</span>;
  }

  return <>
    <button className="header-api-key-button" type="button" onClick={() => setOpen(true)}>
      <KeyRound size={14} aria-hidden="true" /> {l("API Key", "API Key")}
    </button>
    {open ? <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <section className="api-key-modal" role="dialog" aria-modal="true" aria-labelledby="api-key-modal-title">
        <div className="api-key-modal__header">
          <div><span className="eyebrow">LLM</span><h2 id="api-key-modal-title">{l("配置投研 AI 助手", "Configure research AI assistant")}</h2></div>
          <button className="modal-close-button" type="button" onClick={() => setOpen(false)} aria-label={l("关闭", "Close")}>×</button>
        </div>
        {mode !== "research" && mode !== "real" ? <p className="api-key-modal__notice">{l("请切换到 A 股研究模式后使用用户自己的模型 Key。演示和沙盒只保留固定数据。", "Switch to A-share research mode to use your own model key. Demo and sandbox keep fixed data only.")}</p> : null}
        <p className="muted">{l("Key 只用于证据整理、函数调用和报告叙述，不替代风险模型，也不会生成买入或卖出指令。保存后只显示 Key 的摘要。", "The key is used only for evidence organization, function calls, and report narrative. It does not replace risk models or generate buy/sell instructions.")}</p>
        <div className="api-key-modal__form">
          <label><span>{l("配置名称", "Name")}</span><input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>
          <label><span>Endpoint</span><input value={draft.endpoint} onChange={(event) => setDraft((current) => ({ ...current, endpoint: event.target.value }))} /></label>
          <label><span>Model</span><input value={draft.model} onChange={(event) => setDraft((current) => ({ ...current, model: event.target.value }))} /></label>
          <label><span>Key ID</span><input value={draft.credentialId} onChange={(event) => setDraft((current) => ({ ...current, credentialId: event.target.value }))} /></label>
          <label><span>API Key</span><input type="password" value={draft.secret} placeholder={l("输入自己的 Key", "Enter your own key")} onChange={(event) => setDraft((current) => ({ ...current, secret: event.target.value }))} /></label>
        </div>
        <div className="api-key-modal__footer">
          <span className="muted">{activeProfile ? `${l("当前配置", "Current")}: ${activeProfile.name}` : `${credentials.data?.length ?? 0} ${l("个已保存 Key", "saved keys")}`}</span>
          <button className="primary-button" type="button" disabled={configure.isPending || mode !== "research" || !draft.secret} onClick={() => configure.mutate({ profile: { name: draft.name, protocol: "openai_compatible", endpoint: draft.endpoint, model: draft.model, credential_ref: draft.credentialId, timeout_seconds: 20, context_limit: 32000, fallback_profile_id: null, enabled: true }, profileId: activeProfile?.id, credential: { id: draft.credentialId, label: draft.name, secret: draft.secret } })}>
            {configure.isPending ? l("保存中…", "Saving...") : l("保存并启用", "Save and enable")}
          </button>
        </div>
        {configure.isSuccess ? <p className="api-key-modal__success">{l("已保存。下一次 AI 研究解读会使用该配置。", "Saved. The next AI research explanation will use this configuration.")}</p> : null}
        {configure.error ? <p className="api-key-modal__error">{configure.error.message}</p> : null}
      </section>
    </div> : null}
  </>;
}
