import React from "react";
import { AlertTriangle, RefreshCcw, ShieldAlert } from "lucide-react";
import type { PortfolioPayload, ResearchPayload } from "../../components/types";

interface FailureStrategyPanelProps {
  apiState: "loading" | "live" | "fallback";
  error: string | null;
  portfolio: PortfolioPayload;
  research: ResearchPayload;
  onRefresh: () => void;
}

export default function FailureStrategyPanel({ apiState, error, portfolio, research, onRefresh }: FailureStrategyPanelProps) {
  const sourceMissing = !portfolio.sourceMeta || !research.sourceMeta || research.evidence.some((item) => !item.sourceMeta);
  const runMissing = !research.run?.runId;
  const staleData = Boolean(research.qualityGate?.reasons.includes("数据过旧") || research.qualityGate?.expiredEvidenceCount);
  const authFailure = Boolean(error && (error.includes("登录状态") || error.includes("401") || error.includes("CSRF") || error.includes("权限")));
  const degraded = apiState === "fallback" || sourceMissing || runMissing || staleData || authFailure || research.qualityGate?.status === "HOLD" || research.qualityGate?.status === "BLOCK";

  if (!degraded) return null;

  const items = [
    runMissing
      ? {
          title: "无 run",
          detail: "当前研究 payload 没有 run_id，报告入口保持不可用；请重新触发分析生成固定快照。",
          tone: "danger",
        }
      : null,
    sourceMissing
      ? {
          title: "来源缺失",
          detail: "部分接口或证据缺少 sourceMeta，页面只显示观察项，不把结论提升为可采信建议。",
          tone: "warn",
        }
      : null,
    authFailure
      ? {
          title: "CSRF / 401",
          detail: "认证或权限失败时清空本地 token，要求重新登录；不会继续使用旧请求结果。",
          tone: "danger",
        }
      : null,
    staleData
      ? {
          title: "过期数据",
          detail: "证据过期会触发 Judge 降级，用户看到 HOLD/BLOCK，并可手动刷新证据链。",
          tone: "warn",
        }
      : null,
    research.qualityGate?.status === "HOLD" || research.qualityGate?.status === "BLOCK"
      ? {
          title: `Judge ${research.qualityGate.status}`,
          detail: research.qualityGate.summary,
          tone: research.qualityGate.status === "BLOCK" ? "danger" : "warn",
        }
      : null,
  ].filter(Boolean) as Array<{ title: string; detail: string; tone: string }>;

  return (
    <section className="failure-strategy-panel">
      <div className="panel-head">
        <div>
          <h2><ShieldAlert size={18} />关键失败路径展示策略</h2>
          <p>这里把不可采信状态显式展示，避免真实/合成/过期数据在 UI 里混用却不可见。</p>
        </div>
        <button className="ghost-button" onClick={onRefresh} type="button">
          <RefreshCcw size={16} />
          刷新证据
        </button>
      </div>
      <div className="failure-grid">
        {items.map((item) => (
          <article className={`failure-card ${item.tone}`} key={item.title}>
            <AlertTriangle size={17} />
            <div>
              <strong>{item.title}</strong>
              <p>{item.detail}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
