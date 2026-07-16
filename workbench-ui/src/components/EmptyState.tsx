import { ShieldAlert } from "lucide-react";

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <ShieldAlert size={20} aria-hidden="true" />
      <div><strong>{title}</strong><p>{body}</p></div>
    </div>
  );
}
