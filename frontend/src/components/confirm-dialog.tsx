import { useEffect } from "react";

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  isBusy?: boolean;
}

export function ConfirmDialog(props: ConfirmDialogProps) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !props.isBusy) {
        props.onCancel();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [props]);

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={props.isBusy ? undefined : props.onCancel}>
      <section
        className="modal-panel confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="confirm-dialog-title" className="headline">{props.title}</h2>
        </div>
        <div className="confirm-dialog-body">
          <p id="confirm-dialog-message" className="body">{props.message}</p>
        </div>
        <div className="modal-actions">
          <button type="button" className="button secondary" onClick={props.onCancel} disabled={props.isBusy}>
            {props.cancelLabel}
          </button>
          <button type="button" className="button primary danger-confirm" onClick={props.onConfirm} disabled={props.isBusy}>
            {props.confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
