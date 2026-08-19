import { Activity, Clock3, Database, Globe2, KeyRound, LockKeyhole } from "lucide-react";
import { useEffect, useState } from "react";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { ModalPortal } from "../components/ModalPortal";
import { AgentExecutionPanel } from "../features/agent/AgentExecutionPanel";
import { TechnicalAuditHub } from "../features/governance/TechnicalAuditHub";
import { PortfolioPanel } from "../features/overview/PortfolioPanel";
import { FinancialKnowledgePanel } from "../features/research/FinancialKnowledgePanel";
import { HistoricalAnalogyPanel } from "../features/history/HistoricalAnalogyPanel";
import { ResearchPanel } from "../features/research/ResearchPanel";
import { ResearchUserSidebar } from "../features/research/ResearchUserSidebar";
import { useConfigureLLMProviderMutation, useLLMCredentialsQuery, useLLMProviderProfilesQuery } from "../hooks/useWorkbenchQueries";
import { useI18n } from "../i18n";
import { useWorkbenchStore } from "../state/workbenchStore";
import type { LLMProtocol } from "../api/types";
import { ApiError } from "../api/client";

/** Legacy professional layout, kept without account or MCP controls. */
export function WorkbenchPage() {
  const { l, t } = useI18n();
  return (
    <div className="workbench-shell">
      <header className="app-header">
        <div className="brand-lockup"><Activity size={22} aria-hidden="true" /><div><h1>{t("brand.name")}</h1><span>{t("brand.tagline")}</span></div></div>
        <div className="app-header__context" aria-label={t("header.context")}><span><Globe2 size={14} /> {t("header.market")}</span><span><Clock3 size={14} /> {t("header.closeConfirmed")}</span></div>
        <div className="app-header__status"><span className="system-status"><Database size={15} aria-hidden="true" /> {l("公开研究数据", "Public research data")}</span><LanguageSwitch /><LLMApiKeyButton /></div>
      </header>
      <div className="research-mode-banner" role="status">{t("banner.research")}</div>
      <main className="workspace-grid workspace-grid--research">
        <div className="workspace-column workspace-column--research-nav"><PortfolioPanel /><ResearchUserSidebar section="assistant" /></div>
        <div className="workspace-column workspace-column--wide"><ResearchPanel /><details className="short-term-market-observation"><summary><span>{l("短期市场观察", "Short-term market observation")}</span><small>{l("1/5/20 日读数仅用于观察近期波动，不是长期结论或买卖建议", "1/5/20-day readings describe near-term volatility only; they are not a long-term view or trading advice")}</small></summary><AgentExecutionPanel /></details><FinancialKnowledgePanel /><HistoricalAnalogyPanel /></div>
      </main>
      <details className="technical-drawer"><summary><span>{l("技术与审计详情", "Technical and audit details")}</span><small>{l("供模型研究、数据核验和历史回放使用，普通使用无需查看", "For model research, data verification and historical replay; not required for normal use")}</small></summary><TechnicalAuditHub /></details>
    </div>
  );
}

export function WorkbenchPanels() {
  const { l, t } = useI18n();
  return <section className="workbench-panels" aria-labelledby="workbench-panels-title"><h2 id="workbench-panels-title" className="workbench-panels__title">{t("brand.name")}</h2><p className="muted">{t("banner.research")}</p><main className="workspace-grid workspace-grid--research"><div className="workspace-column workspace-column--research-nav"><PortfolioPanel /><ResearchUserSidebar section="assistant" /></div><div className="workspace-column workspace-column--wide"><ResearchPanel /><details className="short-term-market-observation"><summary><span>{l("短期市场观察", "Short-term market observation")}</span></summary><AgentExecutionPanel /></details><FinancialKnowledgePanel /><HistoricalAnalogyPanel /></div></main></section>;
}

/** One project-level configuration, never a visitor account or personal key store. */
export function LLMApiKeyButton() {
  const { l } = useI18n();
  const mode = useWorkbenchStore((state) => state.mode);
  const isPublicDemo = import.meta.env.VITE_PUBLIC_DEMO === "true";
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<{ name: string; protocol: LLMProtocol; endpoint: string; model: string; credentialId: string; secret: string }>({ name: "比赛研究助手", protocol: "openai_compatible", endpoint: "https://api.openai.com/v1/chat/completions", model: "gpt-4o-mini", credentialId: "competition-research", secret: "" });
  const profiles = useLLMProviderProfilesQuery();
  const credentials = useLLMCredentialsQuery();
  const configure = useConfigureLLMProviderMutation();
  const activeProfile = profiles.data?.find((profile) => profile.enabled);

  // Profiles are loaded asynchronously. Hydrate the editable fields from the
  // current project config, but never copy a secret back into the form.
  useEffect(() => {
    if (!activeProfile) return;
    setDraft((current) => ({
      ...current,
      name: activeProfile.name,
      protocol: activeProfile.protocol,
      endpoint: activeProfile.endpoint,
      model: activeProfile.model,
      credentialId: activeProfile.credential_ref ?? current.credentialId,
    }));
  }, [activeProfile]);

  useEffect(() => {
    const openConfig = () => setOpen(true);
    window.addEventListener("open-llm-config", openConfig);
    return () => window.removeEventListener("open-llm-config", openConfig);
  }, []);

  if (isPublicDemo) return <span className="system-status" title={l("比赛演示版使用预置研究能力，不收集访问者的 API Key", "The competition demo uses preconfigured research capability and never collects visitor API keys")}><LockKeyhole size={14} aria-hidden="true" /> {l("项目 AI 已配置", "Project AI configured")}</span>;

  return <>
    <button className="header-api-key-button" type="button" onClick={() => setOpen(true)}><KeyRound size={14} aria-hidden="true" /> {l("项目 AI 设置", "Project AI settings")}</button>
    {open ? <ModalPortal><div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}><section className="api-key-modal" role="dialog" aria-modal="true" aria-labelledby="api-key-modal-title"><div className="api-key-modal__header"><div><span className="eyebrow">AI</span><h2 id="api-key-modal-title">{l("项目 AI 设置", "Project AI settings")}</h2></div><button className="modal-close-button" type="button" onClick={() => setOpen(false)} aria-label={l("关闭", "Close")}>×</button></div><p className="muted">{l("这是比赛项目的统一模型配置，不需要用户登录。Key 仅保存在本机凭证库，页面不会再次展示明文。保存配置不会立即调用外部模型，首次提问时才验证接口。", "This is the competition project's shared model configuration. No user sign-in is required. The key stays in the local credential vault and is never shown again. Saving does not call the external model; the endpoint is checked on the first question.")}</p>{profiles.isError ? <p className="api-key-modal__error">{l("无法读取项目模型配置，请确认本地 8000 后端已启动。", "Unable to read the project model configuration. Check that the local :8000 backend is running.")}</p> : null}<div className="api-key-modal__form"><label><span>{l("配置名称", "Name")}</span><input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label><label><span>{l("接口协议", "Protocol")}</span><select value={draft.protocol} onChange={(event) => setDraft((current) => ({ ...current, protocol: event.target.value as LLMProtocol }))}><option value="openai_compatible">OpenAI-compatible（OpenAI / DeepSeek / Qwen / Kimi / Poe）</option><option value="anthropic_messages">Anthropic Messages</option><option value="gemini_generate_content">Gemini GenerateContent</option><option value="ollama">Ollama（本地）</option></select></label><label><span>Endpoint</span><input value={draft.endpoint} onChange={(event) => setDraft((current) => ({ ...current, endpoint: event.target.value }))} /></label><label><span>Model</span><input value={draft.model} onChange={(event) => setDraft((current) => ({ ...current, model: event.target.value }))} /></label><label><span>Key ID</span><input value={draft.credentialId} onChange={(event) => setDraft((current) => ({ ...current, credentialId: event.target.value }))} /></label><label><span>API Key</span><input type="password" value={draft.secret} placeholder={activeProfile?.credential_ref ? l("已保存 Key，留空则继续使用", "Saved key; leave blank to keep it") : l("输入项目 Key", "Enter the project key")} onChange={(event) => setDraft((current) => ({ ...current, secret: event.target.value }))} /></label></div><div className="api-key-modal__footer"><span className="muted">{activeProfile ? `${l("当前配置", "Current")}: ${activeProfile.name}` : `${credentials.data?.length ?? 0} ${l("个已保存 Key", "saved keys")}`}</span><button className="primary-button" type="button" disabled={configure.isPending || mode !== "research" || (!draft.secret && draft.protocol !== "ollama" && !activeProfile?.credential_ref)} onClick={() => configure.mutate({ profile: { name: draft.name, protocol: draft.protocol, endpoint: draft.endpoint, model: draft.model, credential_ref: draft.secret ? draft.credentialId : (activeProfile?.credential_ref ?? null), timeout_seconds: 20, context_limit: 32000, fallback_profile_id: null, enabled: true }, profileId: activeProfile?.id, credential: draft.secret ? { id: draft.credentialId, label: draft.name, secret: draft.secret } : undefined })}>{configure.isPending ? l("保存中…", "Saving...") : l("保存并启用", "Save and enable")}</button></div>{configure.isSuccess ? <p className="api-key-modal__success">{l("已保存。AI 助手会使用这一项目配置。", "Saved. The AI assistant will use this project configuration.")}</p> : null}{configure.error ? <p className="api-key-modal__error">{configure.error instanceof ApiError && configure.error.kind === "network" ? l("无法连接本地研究服务，请确认 8000 后端已启动。", "Cannot reach the local research service. Check that the :8000 backend is running.") : configure.error.message}</p> : null}</section></div></ModalPortal> : null}
  </>;
}
