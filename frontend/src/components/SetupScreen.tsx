import React, { useState } from "react";
import { LogOut, Plus, Trash2, WalletCards } from "lucide-react";
import ApiKeyPanel from "./ApiKeyPanel";
import type { ApiKeySummary, HoldingInput, PreferenceKey, UserProfile } from "./types";
import { preferenceOptions } from "../preferences";

interface SetupScreenProps {
  user: UserProfile;
  preference: PreferenceKey;
  apiKeys: ApiKeySummary[];
  token: string | null;
  onPreferenceChange: (preference: PreferenceKey) => void;
  onSubmit: (preference: PreferenceKey, riskAnswers: Record<string, unknown>, holdings: HoldingInput[]) => Promise<void>;
  onLogout: () => void;
  onApiKeyChange: () => Promise<void>;
}

export default function SetupScreen({
  user,
  preference,
  apiKeys,
  token,
  onPreferenceChange,
  onSubmit,
  onLogout,
  onApiKeyChange
}: SetupScreenProps) {
  const [riskAnswers, setRiskAnswers] = useState<Record<string, unknown>>({
    horizon: "3-12个月",
    drawdownTolerance: "10%-20%",
    reportFrequency: "weekly"
  });
  const [holdings, setHoldings] = useState<HoldingInput[]>([
    { symbol: "NVDA", name: "NVIDIA", market: "us", shares: "10", costPrice: "120", sector: "AI 算力" }
  ]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateHolding(index: number, patch: Partial<HoldingInput>) {
    setHoldings((current) => current.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(preference, riskAnswers, holdings);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="setup-shell">
      <header className="setup-header">
        <div className="brand">
          <span className="brand-mark">IA</span>
          <div>
            <strong>Investment Agent Workflow</strong>
            <span>{user.email}</span>
          </div>
        </div>
        <button className="ghost-button" onClick={onLogout}>
          <LogOut size={15} />
          退出登录
        </button>
      </header>
      <section className="setup-grid">
        <form className="setup-panel" onSubmit={submit}>
          <p className="eyebrow">Step 1</p>
          <h1>完成前测和持仓录入</h1>
          <p className="muted-text">系统会按你的偏好和真实持仓生成组合风险、证据链、历史类比和观察清单。没有这些输入，就不生成预填好的结论。</p>

          <div className="setup-section">
            <h2>投资偏好</h2>
            <div className="segmented-control">
              {preferenceOptions.map((option) => (
                <button className={option.key === preference ? "selected" : ""} key={option.key} onClick={() => onPreferenceChange(option.key)} type="button" title={option.description}>
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="setup-section two-column-form">
            <label>
              投资周期
              <select value={String(riskAnswers.horizon)} onChange={(event) => setRiskAnswers({ ...riskAnswers, horizon: event.target.value })}>
                <option>1周以内</option>
                <option>1-3个月</option>
                <option>3-12个月</option>
                <option>1年以上</option>
              </select>
            </label>
            <label>
              可接受回撤
              <select value={String(riskAnswers.drawdownTolerance)} onChange={(event) => setRiskAnswers({ ...riskAnswers, drawdownTolerance: event.target.value })}>
                <option>5%以内</option>
                <option>5%-10%</option>
                <option>10%-20%</option>
                <option>20%以上</option>
              </select>
            </label>
            <label>
              报告频率
              <select value={String(riskAnswers.reportFrequency)} onChange={(event) => setRiskAnswers({ ...riskAnswers, reportFrequency: event.target.value })}>
                <option value="daily">每日</option>
                <option value="weekly">每周</option>
                <option value="monthly">每月</option>
                <option value="trigger_only">只在触发时</option>
              </select>
            </label>
          </div>

          <div className="setup-section">
            <div className="section-title-row">
              <h2>我的持仓</h2>
              <button type="button" className="ghost-button" onClick={() => setHoldings([...holdings, { symbol: "", name: "", market: "us", shares: "1", costPrice: "0", sector: "" }])}>
                <Plus size={16} /> 添加
              </button>
            </div>
            <div className="holding-editor">
              {holdings.map((holding, index) => (
                <div className="holding-edit-row" key={`${holding.symbol}-${index}`}>
                  <input placeholder="代码" value={holding.symbol} onChange={(event) => updateHolding(index, { symbol: event.target.value.toUpperCase() })} required />
                  <select value={holding.market} onChange={(event) => updateHolding(index, { market: event.target.value as "us" | "cn" })}>
                    <option value="us">美股/ETF</option>
                    <option value="cn">A股/基金</option>
                  </select>
                  <input placeholder="名称" value={holding.name} onChange={(event) => updateHolding(index, { name: event.target.value })} />
                  <input placeholder="股数/份额" value={holding.shares} onChange={(event) => updateHolding(index, { shares: event.target.value })} type="number" min="0" step="0.01" required />
                  <input placeholder="成本价" value={holding.costPrice} onChange={(event) => updateHolding(index, { costPrice: event.target.value })} type="number" min="0" step="0.01" required />
                  <input placeholder="行业" value={holding.sector} onChange={(event) => updateHolding(index, { sector: event.target.value })} />
                  <button type="button" className="icon-button" onClick={() => setHoldings(holdings.filter((_, i) => i !== index))} aria-label="删除持仓">
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {error ? <p className="form-error">{error}</p> : null}
          <button className="primary-button" disabled={submitting} type="submit">
            <WalletCards size={17} />
            {submitting ? "正在生成数据包..." : "保存并生成投研面板"}
          </button>
        </form>

        <div className="setup-side">
          <ApiKeyPanel apiKeys={apiKeys} token={token} onChange={onApiKeyChange} />
          <section className="setup-panel compact-panel">
            <h2>联网能力说明</h2>
            <p>行情数据优先走 yfinance / AkShare，通常不需要 API Key；LLM 推断、新闻源、付费财务接口可以在这里配置 Key。接口失败时页面会显示不可用，不生成伪实时结论。</p>
          </section>
        </div>
      </section>
    </main>
  );
}
