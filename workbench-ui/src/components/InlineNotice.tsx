type InlineNoticeTone = "info" | "warn" | "block";

export function InlineNotice({
  title,
  body,
  tone = "info"
}: {
  title: string;
  body: string;
  tone?: InlineNoticeTone;
}) {
  const label = tone === "block" ? "BLOCK" : tone === "warn" ? "HOLD" : "INFO";
  return (
    <article className={`story-card story-card--${tone}`}>
      <div className="story-card__header">
        <strong>{title}</strong>
        <span className="tag">{label}</span>
      </div>
      <p>{body}</p>
    </article>
  );
}
