import { AnimatePresence, motion } from "motion/react";
import { Link } from "react-router-dom";
import Meter from "../components/approvals/Meter.jsx";
import Offer from "../components/approvals/Offer.jsx";
import { api, plainPrice } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { useAct } from "../toast.jsx";
import { Avatar } from "../ui.jsx";

const ORDER = { pending: 0, escalated: 1, approved: 2, rejected: 3 };

// The week this screen is about: where most offers deliver, else the first gap week.
function focusWeek(state) {
  const counts = {};
  for (const o of state.offers) if (o.deliver_week) counts[o.deliver_week] = (counts[o.deliver_week] || 0) + 1;
  const busiest = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  if (busiest) return Number(busiest[0]);
  const gap = [...state.forecast].sort((a, b) => a.week - b.week).find((r) => r.is_gap);
  return gap ? gap.week : null;
}

export default function Approvals() {
  const { state } = useLive();
  const act = useAct();
  const week = state ? focusWeek(state) : null;
  const head = (
    <div className="page-head">
      <div>
        <h1>{week ? `Approve gap-fill deals · week ${week}` : "Approve gap-fill deals"}</h1>
        <p>Every offer the agent made waits here. No deal is final until you approve it; the farmer then hears the confirmation by voice.</p>
      </div>
    </div>
  );
  if (!state) {
    return <Shell title="Approvals" head={head}><section className="card offers-card" aria-label="Offers from the agent"><div id="offers" /></section></Shell>;
  }

  const offers = [...state.offers].sort((a, b) => ORDER[a.status] - ORDER[b.status] || (a.created_at || "").localeCompare(b.created_at || ""));
  const limits = Object.fromEntries(state.limits.map((l) => [l.id, l]));
  const quotes = state.rival_quotes.filter((q) => !state.offers.some((o) => o.source === `rival_quote:${q.id}` && ["pending", "approved"].includes(o.status)));
  const l = state.limits[0];
  const anyOut = offers.some((o) => o.status === "escalated");

  return (
    <Shell title="Approvals" head={head}>
      <Meter state={state} week={week} />
      <section className="card offers-card" aria-label="Offers from the agent">
        <div id="offers">
          <AnimatePresence initial={false}>
          {offers.map((o) => <Offer key={o.id} o={o} l={limits[o.crop]} />)}
          {quotes.map((q) => (
            <motion.div layout className="offer" key={q.id} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}>
              <div className="who"><Avatar name={q.supplier_name} cls="ink" /><div><b>{q.supplier_name}</b><span>Logged quote for week {q.deliver_week}, not used yet</span></div></div>
              <div className="fig"><span>Volume</span><b className="num">{(q.kg / 1000).toFixed(1)} t</b></div>
              <div className="fig"><span>Price, {q.currency || "IDR"}/kg</span><b className="num">{plainPrice(q.price_per_kg, q.currency || "IDR")}</b></div>
              <div className="acts"><button className="btn" onClick={() => act(() => api(`/api/rival-quotes/${q.id}/offer`), "Rival quote added as a pending offer.")}>Add as offer</button></div>
            </motion.div>
          ))}
          </AnimatePresence>
          {!offers.length && !quotes.length && (
            <div className="empty">
              <p>No offers yet. Offers appear here as the agent agrees them on gap-fill calls.</p>
              <Link className="btn" to="/">Go to the live forecast</Link>
            </div>
          )}
        </div>
        <div className="offers-foot">
          {l && `${anyOut ? "Offers marked Needs planner asked for more than the ceiling. All others are" : "All offers are"} inside the floor (${plainPrice(l.floor_price, l.currency)}) and ceiling (${plainPrice(l.ceiling_price, l.currency)}). The small bar under each price runs from the floor to the ceiling (black mark); red past it is above the ceiling. Synthetic data.`}
        </div>
      </section>
    </Shell>
  );
}
