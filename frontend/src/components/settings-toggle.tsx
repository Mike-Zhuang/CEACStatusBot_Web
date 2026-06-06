import type { ReactNode } from "react";

interface SettingsToggleProps {
  label: string;
  description?: string;
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
  trailing?: ReactNode;
}

export function SettingsToggle(props: SettingsToggleProps) {
  return (
    <div className="settings-toggle">
      <label className="settings-toggle-main">
        <input
          type="checkbox"
          checked={props.checked}
          onChange={() => props.onChange()}
          disabled={props.disabled}
        />
        <span className="settings-toggle-copy">
          <span className="settings-toggle-label">{props.label}</span>
          {props.description && <span className="settings-toggle-description">{props.description}</span>}
        </span>
      </label>
      {props.trailing}
    </div>
  );
}
