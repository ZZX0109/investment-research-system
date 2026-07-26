import { Panel } from "../../components/Panel";
import { useDomainCatalogQuery } from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";

export function ProvenancePanel() {
  const { l, term } = useI18n();
  const mode = useWorkbenchStore((state) => state.mode);
  const catalogQuery = useDomainCatalogQuery();
  const providerConfig = catalogQuery.data?.analysis_provider_config;
  const providers = catalogQuery.data?.analysis_providers ?? [];
  const activePolicy = catalogQuery.data?.mode_policies.find((policy) => policy.data_mode === mode);

  return (
    <Panel eyebrow={l("治理", "Governance")} title={l("模式策略与数据源", "Mode Policy & Providers")}>
      <article className="story-card">
        <div className="story-card__header">
          <strong>{l("当前模式策略", "Active Mode Policy")}</strong>
          <span className="tag">{term(mode)}</span>
        </div>
        <p>{activePolicy?.description ? term(activePolicy.description) : l("尚未加载模式策略。", "No mode policy loaded.")}</p>
        <ul className="flat-list">
          <li>{l("允许的数据源类型", "Allowed source types")}: {activePolicy?.allowed_source_types.map(term).join(", ") ?? l("暂无", "n/a")}</li>
          <li>{l("评审门禁", "Judge gate")}: {activePolicy?.judge_gate_reason ? term(activePolicy.judge_gate_reason) : l("无默认模式门禁。", "No default mode gate.")}</li>
        </ul>
      </article>
      <article className="story-card">
        <div className="story-card__header">
          <strong>{l("已配置数据源", "Configured Providers")}</strong>
          <span className="tag">{providers.length} {l("个启用", "active")}</span>
        </div>
        <ul className="flat-list">
          <li>{l("市场数据", "Market data")}: {providerConfig?.market_data_provider ?? l("暂无", "n/a")}</li>
          <li>{l("证据数据", "Evidence")}: {providerConfig?.evidence_provider ?? l("暂无", "n/a")}</li>
          {providers.map((provider) => (
            <li key={`${provider.kind}-${provider.provider_name}`}>
              {term(provider.kind)}: {provider.provider_name}@{provider.provider_version}
            </li>
          ))}
        </ul>
      </article>
    </Panel>
  );
}
