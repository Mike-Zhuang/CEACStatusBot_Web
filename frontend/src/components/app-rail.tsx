type ViewMode = "dashboard" | "profile" | "admin";

interface AppRailProps {
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  isAdmin: boolean;
  onAdminSelect: () => void;
  labels: {
    dashboard: string;
    profile: string;
    admin: string;
  };
}

export function AppRail(props: AppRailProps) {
  return (
    <nav className="app-rail" aria-label="Primary">
      <button
        type="button"
        className={`app-rail-item ${props.viewMode === "dashboard" ? "active" : ""}`}
        onClick={() => props.setViewMode("dashboard")}
      >
        <span className="app-rail-short">DB</span>
        <span className="app-rail-label">{props.labels.dashboard}</span>
      </button>
      <button
        type="button"
        className={`app-rail-item ${props.viewMode === "profile" ? "active" : ""}`}
        onClick={() => props.setViewMode("profile")}
      >
        <span className="app-rail-short">ME</span>
        <span className="app-rail-label">{props.labels.profile}</span>
      </button>
      {props.isAdmin && (
        <button
          type="button"
          className={`app-rail-item ${props.viewMode === "admin" ? "active" : ""}`}
          onClick={props.onAdminSelect}
        >
          <span className="app-rail-short">AD</span>
          <span className="app-rail-label">{props.labels.admin}</span>
        </button>
      )}
    </nav>
  );
}
