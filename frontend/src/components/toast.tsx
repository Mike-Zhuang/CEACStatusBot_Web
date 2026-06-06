import { X } from "lucide-react";
import { useToast } from "./use-toast";

export function ToastContainer() {
  const { toasts, dismissToast } = useToast();

  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="toast-stack" aria-live="polite" aria-relevant="additions">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast-item toast-${toast.tone}`} role="status">
          <p className="toast-message">{toast.message}</p>
          <button
            type="button"
            className="icon-button toast-dismiss"
            onClick={() => dismissToast(toast.id)}
            aria-label="Dismiss"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
