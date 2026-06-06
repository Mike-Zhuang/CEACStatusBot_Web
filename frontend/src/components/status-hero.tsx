import type { ReactNode } from "react";

interface StatusHeroProps {
  status: ReactNode;
  statusLabel?: string;
  meta?: Array<{ label: string; value: string }>;
  tone?: "default" | "approved" | "issued" | "negative" | "pending" | "unknown";
}

export function StatusHero(props: StatusHeroProps) {
  const tone = props.tone ?? "default";
  return (
    <section className={`status-hero ${tone}`} aria-label={props.statusLabel}>
      <div className="status-hero-main">
        <p className="status-hero-kicker">{props.statusLabel}</p>
        <div className="status-hero-value">{props.status}</div>
      </div>
      {props.meta && props.meta.length > 0 && (
        <dl className="status-hero-meta">
          {props.meta.map((item) => (
            <div key={item.label} className="status-hero-meta-row">
              <dt>{item.label}</dt>
              <dd className="mono">{item.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
