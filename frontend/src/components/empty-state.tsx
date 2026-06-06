import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  compact?: boolean;
}

export function EmptyState(props: EmptyStateProps) {
  if (props.compact) {
    return (
      <p className="empty-state-inline">
        {props.title}
        {props.action}
      </p>
    );
  }
  return (
    <div className="empty-state">
      <div className="empty-state-copy">
        <h3 className="empty-state-title">{props.title}</h3>
        {props.description && <p className="empty-state-description">{props.description}</p>}
      </div>
      {props.action}
    </div>
  );
}
