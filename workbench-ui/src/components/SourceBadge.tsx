import type { Provenance } from "../api/types";
import { useI18n } from "../i18n";

export function SourceBadge({ provenance }: { provenance: Provenance }) {
  const { term } = useI18n();
  return (
    <span className={`source-badge source-badge--${provenance.source_type}`}>
      {term(provenance.data_mode)} / {term(provenance.source_type)}
    </span>
  );
}
