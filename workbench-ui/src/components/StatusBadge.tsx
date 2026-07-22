import { useI18n } from "../i18n";

const STATUS_KEYS = new Set([
  "complete", "passed", "research_only", "exploratory", "partial", "degraded", "unavailable", "abstain", "blocked",
  "fresh", "stale_usable", "expired", "unsupported", "confirmed_none", "events_present", "fetch_failed"
]);

function statusClass(status: string) {
  return status.toLowerCase().replace(/[^a-z0-9_]+/g, "-");
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const { t } = useI18n();
  const translated = `status.${status}` as Parameters<typeof t>[0];
  return (
    <span className={`status-badge status-badge--${statusClass(status)}`} role="status">
      <span className="status-badge__dot" aria-hidden="true" />
      {label ?? (STATUS_KEYS.has(status) ? t(translated) : status)}
    </span>
  );
}
