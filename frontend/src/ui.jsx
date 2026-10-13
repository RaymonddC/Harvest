import * as RDialog from "@radix-ui/react-dialog";
import { useEffect, useRef, useState } from "react";
import { can, getSession, ICON_PATHS, initials, roleLabel } from "./lib.js";

// Props that switch a control off, with the reason, when the signed-in role lacks the right.
// The server still checks every request.
export const needs = (capability) => (!capability || can(capability) ? {} : { disabled: true, title: `Your role (${roleLabel(getSession())}) cannot do this.` });

export function Icon({ name, size = 18 }) {
  return (
    <span className="icon" aria-hidden="true" style={{ display: "inline-grid", placeItems: "center" }}>
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" dangerouslySetInnerHTML={{ __html: ICON_PATHS[name] || "" }} />
    </span>
  );
}

// person: a soft colour picked from the name, the same every time, so people are easy to tell apart.
const TINTS = 6;
const tintOf = (name = "") => [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % TINTS;
export const Avatar = ({ name, cls = "", person = false }) => (
  <span className={`avatar ${cls} ${person ? `person-tint t${tintOf(name)}` : ""}`.replace(/\s+/g, " ").trim()} aria-hidden="true">{initials(name)}</span>
);

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
export function ActButton({ run, busy: busyText, children, className = "btn", disabled, need, ...rest }) {
  const gate = needs(need);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const click = async (e) => {
    setBusy(true);
    try { await run(e); } finally { if (alive.current) setBusy(false); }
  };
  return (
    <button type="button" className={className} disabled={disabled || busy || gate.disabled} aria-busy={busy || undefined} onClick={click} {...rest} title={gate.title || rest.title}>
      {busy ? <><Spinner />{busyText}</> : children}
    </button>
  );
}

export const Spinner = () => <span className="spinner" aria-hidden="true" />;

// The submit button of a form whose save is running.
export const SubmitButton = ({ busy, busyText, children, className = "btn solid" }) => (
  <button type="submit" className={className} disabled={busy} aria-busy={busy || undefined}>{busy ? <><Spinner />{busyText}</> : children}</button>
);
