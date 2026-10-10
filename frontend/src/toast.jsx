import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast, Toaster } from "sonner";
import { clearSession, getSession } from "./lib.js";

// Toasts sit at the bottom centre, above the phone tab bar, in the app's ink and danger colours
// (see .hc-toast in react.css).
export function Toasts() {
  return (
    <Toaster position="bottom-center" offset={24} gap={8} visibleToasts={3}
      toastOptions={{ unstyled: true, classNames: { toast: "hc-toast", error: "hc-toast error", actionButton: "hc-toast-action" } }} />
  );
}

// Run a planner action. Viewers are told why nothing happens; an expired session goes back
// to sign-in. ok is the success message, or a function of the result returning one; undo, when
// given, puts an "Undo" button on the toast that runs it.
// Resolves to the action's result, or undefined when it did not run.
export function useAct() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return useCallback(async function act(fn, ok, undo) {
    const session = getSession();
    if (session && session.role !== "planner") {
      toast.error("You are signed in as a viewer. Switch to the Planner role to change anything.");
      return undefined;
    }
    try {
      const result = await fn();
      const message = typeof ok === "function" ? ok(result) : ok;
      if (message) toast(message, undo ? { action: { label: "Undo", onClick: () => act(undo.fn, undo.ok) } } : undefined);
      return result;
    } catch (err) {
      if (err.status === 401) {
        clearSession();
        navigate(`/login?next=${encodeURIComponent(pathname)}&expired=1`, { replace: true });
        return undefined;
      }
      toast.error(err.message);
      return undefined;
    }
  }, [navigate, pathname]);
}
