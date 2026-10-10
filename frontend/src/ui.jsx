import * as RDialog from "@radix-ui/react-dialog";
import { useEffect, useRef, useState } from "react";
import { ICON_PATHS, initials } from "./lib.js";

export function Icon({ name, size = 18 }) {
  return (
    <span className="icon" aria-hidden="true" style={{ display: "inline-grid", placeItems: "center" }}>
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" dangerouslySetInnerHTML={{ __html: ICON_PATHS[name] || "" }} />
    </span>
  );
}

export const Avatar = ({ name, cls = "" }) => <span className={`avatar ${cls}`.trim()} aria-hidden="true">{initials(name)}</span>;

export const Pill = ({ children, cls = "" }) => <span className={`pill ${cls}`.trim()}>{children}</span>;

// A modal (Radix): focus stays inside, Esc and the overlay close it, and focus returns to the
// button that opened it. Put <DialogClose> on any button that should close it.
export function Dialog({ open, onClose, title, children, wide }) {
  return (
    <RDialog.Root open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <RDialog.Portal>
        <RDialog.Overlay className="hc-overlay" />
        <RDialog.Content className={`hc-dialog ${wide ? "wide" : ""}`} aria-describedby={undefined}>
          <RDialog.Title className="hc-dialog-title">{title}</RDialog.Title>
          {children}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export const DialogClose = ({ children = "Close" }) => (
  <RDialog.Close asChild><button className="btn" type="button">{children}</button></RDialog.Close>
);

// A button for a server action. run() returns a promise; while it runs the button is disabled,
// shows a small spinner and says what is happening ("Approving…"), so nobody clicks twice.
export function ActButton({ run, busy: busyText, children, className = "btn", disabled, ...rest }) {
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const click = async (e) => {
    setBusy(true);
    try { await run(e); } finally { if (alive.current) setBusy(false); }
  };
  return (
    <button type="button" className={className} disabled={disabled || busy} aria-busy={busy || undefined} onClick={click} {...rest}>
      {busy ? <><Spinner />{busyText}</> : children}
    </button>
  );
}

export const Spinner = () => <span className="spinner" aria-hidden="true" />;

// The submit button of a form whose save is running.
export const SubmitButton = ({ busy, busyText, children, className = "btn solid" }) => (
  <button type="submit" className={className} disabled={busy} aria-busy={busy || undefined}>{busy ? <><Spinner />{busyText}</> : children}</button>
);
