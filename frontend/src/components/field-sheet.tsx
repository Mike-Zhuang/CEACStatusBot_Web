import type { ReactNode } from "react";

export interface FieldSheetItem {
  label: string;
  value?: string;
  children?: ReactNode;
  mono?: boolean;
}

interface FieldSheetProps {
  title?: string;
  fields: FieldSheetItem[];
}

export function FieldSheet(props: FieldSheetProps) {
  return (
    <section className="field-sheet">
      {props.title && <h3 className="field-sheet-title">{props.title}</h3>}
      <dl className="field-sheet-grid">
        {props.fields.map((field) => (
          <div key={field.label} className="field-sheet-row">
            <dt className="field-sheet-label">{field.label}</dt>
            <dd className={`field-sheet-value ${field.mono ? "mono" : ""}`}>
              {field.children ?? field.value ?? "—"}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
