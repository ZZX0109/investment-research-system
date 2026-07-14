import type { PropsWithChildren, ReactNode } from "react";

interface PanelProps extends PropsWithChildren {
  eyebrow: string;
  title: string;
  actions?: ReactNode;
}

export function Panel({ eyebrow, title, actions, children }: PanelProps) {
  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h2>{title}</h2>
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}
