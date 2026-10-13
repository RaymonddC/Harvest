import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { getSession } from "./lib.js";
import { useLive } from "./live.jsx";

const WAITING = ["pending", "escalated"];
const ENDED = ["done", "declined", "dropped"];

// Tells the planner when something needs them, wherever they are in the app: new offers to
// decide on, and calls that have just ended. Nothing is shown for what was already there when
// the page opened.
export default function Alerts() {
  const { state } = useLive();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const seen = useRef(null);
  useEffect(() => {
    if (!state) return;
    const offers = new Set(state.offers.filter((o) => WAITING.includes(o.status)).map((o) => o.id));
    const ended = new Set(state.calls.filter((c) => ENDED.includes(c.status)).map((c) => c.id));
    const before = seen.current;
    seen.current = { offers, ended };
    if (!before || !getSession() || pathname === "/login") return;

    const newOffers = [...offers].filter((id) => !before.offers.has(id)).length;
    if (newOffers && pathname !== "/approvals") {
      toast(newOffers === 1 ? "A new offer is waiting for your decision." : `${newOffers} new offers are waiting for your decision.`,
        { action: { label: "Review", onClick: () => navigate("/approvals") } });
    }
    const newEnded = state.calls.filter((c) => ended.has(c.id) && !before.ended.has(c.id));
    if (newEnded.length === 1) {
      const c = newEnded[0];
      toast(c.status === "done" ? `Call with ${c.farmer_name} finished.` : `Call with ${c.farmer_name} ${c.status === "declined" ? "was declined" : "dropped"}.`,
        pathname !== "/" ? { action: { label: "Forecast", onClick: () => navigate("/") } } : undefined);
    } else if (newEnded.length > 1) {
      toast(`${newEnded.length} calls finished.`, pathname !== "/" ? { action: { label: "Forecast", onClick: () => navigate("/") } } : undefined);
    }
  }, [state]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}
