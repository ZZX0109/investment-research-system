import { Panel } from "../../components/Panel";
import { useDomainCatalogQuery } from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";

export function ProvenancePanel() {
  const mode = useWorkbenchStore((state) => state.mode);
  const catalogQuery = useDomainCatalogQuery();
  const providerConfig = catalogQuery.data?.analysis_provider_config;
  const providers = catalogQuery.data?.analysis_providers ?? [];
  const activePolicy = catalogQuery.data?.mode_policies.find((policy) => policy.data_mode === mode);

  return (
    <Panel eyebrow="Governance" title="Mode Policy & Providers">
      <article className="story-card">
        <div className="story-card__header">
          <strong>Active Mode Policy</strong>
          <span className="tag">{mode}</span>
        </div>
        <p>{activePolicy?.description ?? "No mode policy loaded."}</p>
        <ul className="flat-list">
          <li>Allowed source types: {activePolicy?.allowed_source_types.join(", ") ?? "n/a"}</li>
          <li>Judge gate: {activePolicy?.judge_gate_reason ?? "No default mode gate."}</li>
        </ul>
      </article>
      <article className="story-card">
        <div className="story-card__header">
          <strong>Configured Providers</strong>
          <span className="tag">{providers.length} active</span>
        </div>
        <ul className="flat-list">
          <li>Market data: {providerConfig?.market_data_provider ?? "n/a"}</li>
          <li>Evidence: {providerConfig?.evidence_provider ?? "n/a"}</li>
          {providers.map((provider) => (
            <li key={`${provider.kind}-${provider.provider_name}`}>
              {provider.kind}: {provider.provider_name}@{provider.provider_version}
            </li>
          ))}
        </ul>
      </article>
    </Panel>
  );
}
