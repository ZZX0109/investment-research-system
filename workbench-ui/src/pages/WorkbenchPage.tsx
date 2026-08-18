import { LanguageSwitch } from "../components/LanguageSwitch";
import { useI18n } from "../i18n";
import { Activity, Clock3, Copy, Database, Globe2, KeyRound, Link2, LockKeyhole, Trash2 } from "lucide-react";
import { AuthCard } from "../features/auth/AuthCard";
import { TechnicalAuditHub } from "../features/governance/TechnicalAuditHub";
import { PortfolioPanel } from "../features/overview/PortfolioPanel";
import { ResearchUserSidebar } from "../features/research/ResearchUserSidebar";
import { ResearchPanel } from "../features/research/ResearchPanel";
import { FinancialKnowledgePanel } from "../features/research/FinancialKnowledgePanel";
import { HistoricalAnalogyPanel } from "../features/history/HistoricalAnalogyPanel";
import { useWorkbenchStore } from "../state/workbenchStore";
import { AgentExecutionPanel } from "../features/agent/AgentExecutionPanel";
import { useConfigureLLMProviderMutation, useCreateWorkBuddyConnectionMutation, useLLMCredentialsQuery, useLLMProviderProfilesQuery, useRevokeWorkBuddyConnectionMutation, useWorkBuddyConnectionsQuery } from "../hooks/useWorkbenchQueries";
import type { LLMProtocol } from "../api/types";
import { useEffect, useState } from "react";

export function WorkbenchPage() {
  const mode = useWorkbenchStore((state) => state.mode);
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
          <span className="system-status"><Database size={15} aria-hidden="true" /> {l("公开研究数据", "Public research data")}</span>
          <span className="system-status"><Globe2 size={15} aria-hidden="true" /> {l("来源：AKShare / Baostock", "Sources: AKShare / Baostock")}</span>
          <LanguageSwitch />
          <LLMApiKeyButton />
          <WorkBuddyConnectorButton />
        </div>
      </header>

      <div className="research-mode-banner" role="status">
        {t("banner.research")}
      </div>

      <main className="workspace-grid workspace-grid--research">
        <div className="workspace-column workspace-column--research-nav">
          <div className="research-sidebar-auth"><AuthCard /></div>
          <PortfolioPanel />
          <ResearchUserSidebar section="assistant" />
        </div>
        <div className="workspace-column workspace-column--wide">
          <ResearchPanel />
          <details className="short-term-market-observation" data-testid="short-term-market-observation">
            <summary>
              <span>{l("短期市场观察", "Short-term market observation")}</span>
              <small>{l("1/5/20 日读数仅用于观察近期波动，不是长期结论或买卖建议", "1/5/20-day readings describe near-term volatility only; they are not a long-term view or trading advice")}</small>
            </summary>
            <AgentExecutionPanel />
          </details>
          <FinancialKnowledgePanel />
          <HistoricalAnalogyPanel />
        </div>
      </main>
      <details className="technical-drawer">
        <summary>
          <span>{l("技术与审计详情", "Technical and audit details")}</span>
          <small>{l("供模型研究、数据核验和历史回放使用，普通使用无需查看", "For model research, data verification and historical replay; not required for normal use")}</small>
        </summary>
        <TechnicalAuditHub />
      </details>
    </div>
  );
}

function LLMApiKeyButton() {
  const { l } = useI18n();
  const isPublicDemo = import.meta.env.VITE_PUBLIC_DEMO === "true";
  const mode = useWorkbenchStore((state) => state.mode);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<{ name: string; protocol: LLMProtocol; endpoint: string; model: string; credentialId: string; secret: string }>({ name: "研究助手", protocol: "openai_compatible", endpoint: "https://api.openai.com/v1/chat/completions", model: "gpt-4o-mini", credentialId: "research-openai", secret: "" });
  const profiles = useLLMProviderProfilesQuery();
  const credentials = useLLMCredentialsQuery();
  const configure = useConfigureLLMProviderMutation();
  const activeProfile = profiles.data?.find((profile) => profile.enabled);

  useEffect(() => {
    const openConfig = () => setOpen(true);
    window.addEventListener("open-llm-config", openConfig);
    return () => window.removeEventListener("open-llm-config", openConfig);
  }, []);

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
        {profiles.isError ? <p className="api-key-modal__error">{l("当前登录会话无法读取模型配置，请重新登录后再打开此窗口。", "The current session cannot read model configuration. Sign in again and reopen this window.")}</p> : null}
        <p className="muted">{l("Key 只用于证据整理、函数调用和报告叙述，不替代风险模型，也不会生成买入或卖出指令。保存后只显示 Key 的摘要。", "The key is used only for evidence organization, function calls, and report narrative. It does not replace risk models or generate buy/sell instructions.")}</p>
        <div className="api-key-modal__form">
          <label><span>{l("配置名称", "Name")}</span><input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>
          <label><span>{l("接口协议", "Protocol")}</span><select value={draft.protocol} onChange={(event) => setDraft((current) => ({ ...current, protocol: event.target.value as LLMProtocol }))}>
            <option value="openai_compatible">OpenAI-compatible（OpenAI / DeepSeek / Qwen / Kimi / Poe）</option>
            <option value="anthropic_messages">Anthropic Messages</option>
            <option value="gemini_generate_content">Gemini GenerateContent</option>
            <option value="ollama">Ollama（本地）</option>
          </select></label>
          <label><span>Endpoint</span><input value={draft.endpoint} onChange={(event) => setDraft((current) => ({ ...current, endpoint: event.target.value }))} /></label>
          <label><span>Model</span><input value={draft.model} onChange={(event) => setDraft((current) => ({ ...current, model: event.target.value }))} /></label>
          <label><span>Key ID</span><input value={draft.credentialId} onChange={(event) => setDraft((current) => ({ ...current, credentialId: event.target.value }))} /></label>
          <label><span>API Key</span><input type="password" value={draft.secret} placeholder={l("输入自己的 Key", "Enter your own key")} onChange={(event) => setDraft((current) => ({ ...current, secret: event.target.value }))} /></label>
        </div>
        <div className="api-key-modal__footer">
          <span className="muted">{activeProfile ? `${l("当前配置", "Current")}: ${activeProfile.name}` : `${credentials.data?.length ?? 0} ${l("个已保存 Key", "saved keys")}`}</span>
          <button className="primary-button" type="button" disabled={configure.isPending || mode !== "research" || (!draft.secret && draft.protocol !== "ollama")} onClick={() => configure.mutate({ profile: { name: draft.name, protocol: draft.protocol, endpoint: draft.endpoint, model: draft.model, credential_ref: draft.secret ? draft.credentialId : null, timeout_seconds: 20, context_limit: 32000, fallback_profile_id: null, enabled: true }, profileId: activeProfile?.id, credential: draft.secret ? { id: draft.credentialId, label: draft.name, secret: draft.secret } : undefined })}>
            {configure.isPending ? l("保存中…", "Saving...") : l("保存并启用", "Save and enable")}
          </button>
        </div>
        {configure.isSuccess ? <p className="api-key-modal__success">{l("已保存。下一次 AI 研究解读会使用该配置。", "Saved. The next AI research explanation will use this configuration.")}</p> : null}
        {configure.error ? <p className="api-key-modal__error">{configure.error.message}</p> : null}
      </section>
    </div> : null}
  </>;
}

function WorkBuddyConnectorButton() {
  const { l } = useI18n();
  const mode = useWorkbenchStore((state) => state.mode);
  const isPublicDemo = import.meta.env.VITE_PUBLIC_DEMO === "true";
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("WorkBuddy 研究助手");
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const connections = useWorkBuddyConnectionsQuery();
  const create = useCreateWorkBuddyConnectionMutation();
  const revoke = useRevokeWorkBuddyConnectionMutation();
  const mcpUrl = typeof window === "undefined" ? "/api/v1/workbuddy/mcp" : `${window.location.origin}/api/v1/workbuddy/mcp`;
  if (isPublicDemo || mode !== "research") return null;
  return <>
    <button className="header-api-key-button" type="button" onClick={() => setOpen(true)}>
      <Link2 size={14} aria-hidden="true" /> MCP
    </button>
    {open ? <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <section className="api-key-modal workbuddy-modal" role="dialog" aria-modal="true" aria-labelledby="workbuddy-modal-title">
        <div className="api-key-modal__header"><div><span className="eyebrow">WorkBuddy / MCP</span><h2 id="workbuddy-modal-title">{l("连接 WorkBuddy", "Connect WorkBuddy")}</h2></div><button className="modal-close-button" type="button" onClick={() => setOpen(false)} aria-label={l("关闭", "Close")}>×</button></div>
        <p className="muted">{l("连接器只能读取研究结果、数据质量、Shadow 和知识库；不能训练模型、修改参数、发布模型或下单。", "The connector can only read research, data quality, Shadow and knowledge. It cannot train, change parameters, publish models or trade.")}</p>
        <label className="workbuddy-modal__name"><span>{l("连接名称", "Connection name")}</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
        <div className="workbuddy-modal__config"><strong>{l("MCP 地址", "MCP URL")}</strong><code>{mcpUrl}</code><button className="ghost-button" type="button" onClick={() => void navigator.clipboard?.writeText(mcpUrl)}><Copy size={14} /> {l("复制", "Copy")}</button></div>
        {issuedToken ? <div className="workbuddy-modal__token"><strong>{l("连接令牌（仅显示一次）", "Connection token (shown once)")}</strong><code>{issuedToken}</code><button className="ghost-button" type="button" onClick={() => void navigator.clipboard?.writeText(issuedToken)}><Copy size={14} /> {l("复制", "Copy")}</button><p>{l("在 WorkBuddy 的 MCP 设置中填写上述地址，并以 Authorization: Bearer &lt;令牌&gt; 配置鉴权。", "In WorkBuddy MCP settings, use the URL above and set Authorization: Bearer &lt;token&gt;.")}</p></div> : <button className="primary-button" type="button" disabled={create.isPending || !name.trim()} onClick={() => create.mutate({ name: name.trim() }, { onSuccess: (result) => setIssuedToken(result.token) })}><Link2 size={15} /> {create.isPending ? l("创建中…", "Creating...") : l("生成连接令牌", "Create connector token")}</button>}
        {create.error ? <p className="api-key-modal__error">{create.error.message}</p> : null}
        <div className="workbuddy-modal__connections"><strong>{l("已有连接", "Existing connections")}</strong>{connections.data?.length ? connections.data.map((item) => <div key={item.id}><span>{item.name} · {item.token_prefix}…</span><button className="ghost-button" type="button" disabled={revoke.isPending} onClick={() => revoke.mutate(item.id)}><Trash2 size={14} /> {l("撤销", "Revoke")}</button></div>) : <p className="muted">{l("尚未创建连接。", "No connector yet.")}</p>}</div>
      </section>
    </div> : null}
  </>;
}
