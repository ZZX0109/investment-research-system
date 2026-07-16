export function EvidenceHash({ label, value }: { label: string; value?: string | null }) {
  const compact = value ? `${value.slice(0, 10)}…${value.slice(-6)}` : "unavailable";
  return (
    <span className="evidence-hash" title={value ?? undefined}>
      <span>{label}</span><code>{compact}</code>
    </span>
  );
}
