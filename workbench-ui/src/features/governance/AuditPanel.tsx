import { Panel } from "../../components/Panel";
import { useAuditRecordsQuery } from "../../hooks/useWorkbenchQueries";

export function AuditPanel() {
  const auditQuery = useAuditRecordsQuery();

  return (
    <Panel eyebrow="Governance" title="Audit Trail">
      <div className="stack-list">
        {(auditQuery.data ?? []).map((record) => (
          <article className="story-card" key={record.id}>
            <div className="story-card__header">
              <strong>{record.action}</strong>
              <span className="tag">{record.target_type}</span>
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
