import { AnimatePresence, motion } from "motion/react";
import { Link } from "react-router-dom";
import Meter from "../components/approvals/Meter.jsx";
import Offer from "../components/approvals/Offer.jsx";
import { api, plainPrice } from "../lib.js";
import { forCrop, useCrop } from "../campaigns.jsx";
import { useConfirm } from "../dialogs.jsx";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { useAct } from "../toast.jsx";
import { ActButton, Avatar, Icon } from "../ui.jsx";

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
  const confirm = useConfirm();
  const { crop } = useCrop();
  // Only the picked crop's offers and quotes.
  const view = state ? { ...state, offers: forCrop(state.offers, crop), forecast: forCrop(state.forecast, crop), rival_quotes: forCrop(state.rival_quotes, crop) } : null;
  const week = view ? focusWeek(view) : null;
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

  const offers = [...view.offers].sort((a, b) => ORDER[a.status] - ORDER[b.status] || (a.created_at || "").localeCompare(b.created_at || ""));
  const limits = Object.fromEntries(state.limits.map((l) => [l.id, l]));
  const quotes = view.rival_quotes.filter((q) => !view.offers.some((o) => o.source === `rival_quote:${q.id}` && ["pending", "approved"].includes(o.status)));
  const l = state.limits.find((x) => (x.crop || x.id) === crop) || null; // a crop without a price range shows none, not another crop's
  const anyOut = offers.some((o) => o.status === "escalated");
  const rowOf = Object.fromEntries(view.forecast.map((r) => [r.week, r]));
  const toDecide = offers.filter((o) => o.status === "pending" || o.status === "escalated");
  const decided = offers.filter((o) => o.status === "approved" || o.status === "rejected");
  // Pending offers whose price sits inside the floor and ceiling: safe to approve in one go.
  const fits = (o) => { const x = limits[o.crop]; return x && o.price_per_kg >= x.floor_price && o.price_per_kg <= x.ceiling_price; };
  const easy = toDecide.filter((o) => o.status === "pending" && fits(o));
  const approveAll = async () => {
    const kg = easy.reduce((n, o) => n + o.kg, 0);
    const ok = await confirm({ title: `Approve ${easy.length} offers?`,
      body: `All ${easy.length} are inside the price range, ${(kg / 1000).toFixed(1)} t in total. Each farmer gets a confirmation call. You can undo right after.`,
      confirm: `Approve ${easy.length} offers` });
    if (!ok) return;
    const ids = easy.map((o) => o.id);
    await act(async () => { for (const id of ids) await api(`/api/offers/${id}/approve`); },
      `${ids.length} offers approved. Confirmation calls are queued.`,
      { fn: async () => { for (const id of ids) await api(`/api/offers/${id}/undo`); }, ok: "Back to pending." });
  };
  const gap = [...view.forecast].sort((a, b) => a.week - b.week).find((r) => r.is_gap);
  const group = (title, n, extra) => <div className="offer-group"><h3>{title}<span className="count">{n}</span></h3>{extra}</div>;

  return (
    <Shell title="Approvals" head={head}>
      {/* Offers on the left; the week's gap and totals stay in view on the right. */}
      <div className="cols approvals-cols">
      <div className="col-main">
      <section className="card offers-card" aria-label="Offers from the agent">
        <div id="offers">
          {toDecide.length > 0 && group("Needs your decision", toDecide.length, easy.length > 1 && (
            <ActButton need="offers.decide" className="btn leaf" busy="Approving…" run={approveAll}>
              <Icon name="approvals" size={15} />Approve {easy.length} within the price range
            </ActButton>
          ))}
          <AnimatePresence initial={false}>
          {toDecide.map((o) => <Offer key={o.id} o={o} l={limits[o.crop]} row={rowOf[o.deliver_week]} />)}
          </AnimatePresence>
          {quotes.length > 0 && group("Rival quotes not used yet", quotes.length)}
          <AnimatePresence initial={false}>
          {quotes.map((q) => (
            <motion.div layout className="offer" key={q.id} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}>
              <div className="who"><Avatar name={q.supplier_name} cls="ink" /><div><b>{q.supplier_name}</b><span>Logged quote for week {q.deliver_week}, not used yet</span></div></div>
              <div className="fig"><span>Volume</span><b className="num">{(q.kg / 1000).toFixed(1)} t</b></div>
              <div className="fig"><span>Price, {q.currency || "IDR"}/kg</span><b className="num">{plainPrice(q.price_per_kg, q.currency || "IDR")}</b></div>
              <div className="acts"><ActButton need="offers.decide" busy="Adding…" run={() => act(() => api(`/api/rival-quotes/${q.id}/offer`), "Rival quote added as a pending offer.")}>Add as offer</ActButton></div>
            </motion.div>
          ))}
          </AnimatePresence>
          {decided.length > 0 && group("Decided", decided.length)}
          <AnimatePresence initial={false}>
          {decided.map((o) => <Offer key={o.id} o={o} l={limits[o.crop]} row={rowOf[o.deliver_week]} />)}
          </AnimatePresence>
          {!offers.length && !quotes.length && (
            <div className="empty">
              {gap ? (
                <>
                  <p>No offers yet. Week {gap.week} is {(gap.gap_kg / 1000).toFixed(0)} t short: gap-fill calls ask farmers to move harvest into it, and every deal they agree lands here.</p>
                  <ActButton need="campaign.run" className="btn solid" busy="Queuing calls…"
                    run={() => act(() => api("/api/campaign/start", { body: { kind: "gap_fill", crop } }), (r) => `${r.queued} gap-fill calls queued. Answer them in the call client.`)}>
                    <Icon name="phone" size={16} />Start gap-fill calls
                  </ActButton>
                </>
              ) : (
                <>
                  <p>No offers yet, and no week is short right now. Offers appear here when the agent agrees them on gap-fill calls.</p>
                  <Link className="btn" to="/">Go to the live forecast</Link>
                </>
              )}
            </div>
          )}
        </div>
        <div className="offers-foot">
          {l && `Price range: floor ${plainPrice(l.floor_price, l.currency)}, ceiling ${plainPrice(l.ceiling_price, l.currency)}. The bar under each price shows where it sits; red is above the ceiling${anyOut ? " (marked Needs planner)" : ""}. Synthetic data.`}
        </div>
      </section>
      </div>
      <div className="col-side"><Meter state={view} week={week} offers={view.offers} /></div>
      </div>
    </Shell>
  );
}
