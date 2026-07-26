import { Panel } from "../../components/Panel";
import { useAuditRecordsQuery } from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";

export function AuditPanel() {
  const { l, term } = useI18n();
  const auditQuery = useAuditRecordsQuery();

  return (
    <Panel eyebrow={l("治理", "Governance")} title={l("审计记录", "Audit Trail")}>
      <div className="stack-list">
        {(auditQuery.data ?? []).map((record) => (
          <article className="story-card" key={record.id}>
            <div className="story-card__header">
              <strong>{term(record.action)}</strong>
              <span className="tag">{term(record.target_type)}</span>
            </div>
            <p className="muted mono">{record.created_at}</p>
            <p className="muted">
              {Object.entries(record.details)
                .map(([key, value]) => `${key}: ${value}`)
                .join(" · ")}
            </p>
          </article>
        ))}
      </div>
    </Panel>
  );
}
