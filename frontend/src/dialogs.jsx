import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Dialog } from "./ui.jsx";

// ---------- confirm: the app's own dialog instead of the browser's confirm() ----------

const Confirm = createContext(async () => false);

// const ok = await confirm({ title, body, confirm: "Delete", danger: true })
export function ConfirmProvider({ children }) {
  const [ask, setAsk] = useState(null);
  const confirm = useCallback((opts) => new Promise((resolve) => setAsk({ ...opts, resolve })), []);
  const answer = (yes) => { ask?.resolve(yes); setAsk(null); };
  return (
    <Confirm.Provider value={confirm}>
      {children}
      <Dialog open={!!ask} onClose={() => answer(false)} title={ask?.title || ""}>
        {ask?.body && <p className="confirm-body">{ask.body}</p>}
        <div className="confirm-acts">
          <button type="button" className={`btn ${ask?.danger ? "danger-solid" : "solid"}`} onClick={() => answer(true)} autoFocus>{ask?.confirm || "OK"}</button>
          <button type="button" className="btn" onClick={() => answer(false)}>{ask?.cancel || "Cancel"}</button>
        </div>
      </Dialog>
    </Confirm.Provider>
  );
}

export const useConfirm = () => useContext(Confirm);

// ---------- unsaved changes: a form says it has edits; leaving asks first ----------

const Unsaved = createContext({ unsaved: false, setUnsaved: () => {}, guard: async () => true });

export function UnsavedProvider({ children }) {
  const [unsaved, setUnsaved] = useState(false);
  const confirm = useConfirm();
  const ref = useRef(false);
  ref.current = unsaved;
  // Closing or reloading the tab: the browser's own prompt is the only one allowed there.
  useEffect(() => {
    const onLeave = (e) => { if (ref.current) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", onLeave);
    return () => window.removeEventListener("beforeunload", onLeave);
  }, []);
  // Moving to another page inside the app: resolves true when it is fine to go.
  const guard = useCallback(async () => {
    if (!ref.current) return true;
    const go = await confirm({ title: "Leave without saving?", body: "You changed the price range but did not save it. Leaving drops those changes.",
      confirm: "Leave without saving", cancel: "Stay on this page", danger: true });
    if (go) setUnsaved(false);
    return go;
  }, [confirm]);
  return <Unsaved.Provider value={{ unsaved, setUnsaved, guard }}>{children}</Unsaved.Provider>;
}

export const useUnsaved = () => useContext(Unsaved);
