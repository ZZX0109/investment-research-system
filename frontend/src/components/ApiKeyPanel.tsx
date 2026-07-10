import React, { useState } from "react";
import { KeyRound, Save } from "lucide-react";
import type { ApiKeySummary } from "./types";
import { apiRequest } from "../lib/apiClient";

interface ApiKeyPanelProps {
  apiKeys: ApiKeySummary[];
  token: string | null;
  onChange: () => Promise<void>;
  compact?: boolean;
}

export default function ApiKeyPanel({ apiKeys, token, onChange, compact = false }: ApiKeyPanelProps) {
  const [provider, setProvider] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;
    try {
      await apiRequest<{ apiKeys: ApiKeySummary[] }>("/api/api-keys", token, {
        method: "POST",
        body: JSON.stringify({ provider, apiKey })
      });
      setApiKey("");
      setMessage(`${provider} 已保存，页面只显示掩码。`);
      await onChange();
    } catch (err) {
      setMessage((err as Error).message);
    }
  }

  return (
    <section className={`api-key-panel ${compact ? "compact" : ""}`}>
      <div className="panel-head">
        <div>
          <h2>
            <KeyRound size={18} />
            API Key 管理
          </h2>
          <p>用于 LLM、新闻和付费数据源；本地只返回掩码，不在页面暴露完整 Key。</p>
        </div>
      </div>
      <form className="api-key-form" onSubmit={save}>
        <select value={provider} onChange={(event) => setProvider(event.target.value)}>
          <option value="openai">OpenAI</option>
          <option value="alpha_vantage">Alpha Vantage</option>
          <option value="financial_modeling_prep">FMP</option>
          <option value="tushare">Tushare</option>
          <option value="newsapi">NewsAPI</option>
        </select>
        <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="粘贴 API Key" type="password" />
        <button className="primary-button" type="submit">
          <Save size={15} />
          保存
        </button>
      </form>
      {message ? <p className="muted-text">{message}</p> : null}
      <div className="api-key-list">
        {apiKeys.length ? (
          apiKeys.map((item) => (
            <span key={item.provider}>
              {item.provider}: {item.maskedKey}
            </span>
          ))
        ) : (
          <span>尚未配置外部 Key。行情接口仍可尝试联网获取。</span>
        )}
      </div>
    </section>
  );
}
