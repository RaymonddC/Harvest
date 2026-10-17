import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Messages from "../components/approvals/Messages.jsx";
import Meter from "../components/approvals/Meter.jsx";
import Offer from "../components/approvals/Offer.jsx";
import { api, gapFillBody, gapFillToast, plainPrice, startUrl } from "../lib.js";
import { forCrop, inCampaign, useCrop } from "../campaigns.jsx";
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
  const { cid, crop } = useCrop();
  // What approving each waiting offer would do (weeks, cost, new gaps), fetched again when offers change.
  const [impact, setImpact] = useState(null);
  const [impactFailed, setImpactFailed] = useState(false);
  const offersKey = state ? JSON.stringify(state.offers.map((o) => [o.id, o.status, o.kg])) + JSON.stringify(state.forecast.map((r) => r.expected_kg)) : "";
  useEffect(() => {
    if (!state) return undefined;
    let live = true;
    const t = setTimeout(() => api(`/api/approvals/impact?campaign=${encodeURIComponent(cid)}`, { method: "GET" })
      .then((r) => { if (live) { setImpact(r); setImpactFailed(false); } }).catch(() => { if (live) setImpactFailed(true); }), 300);
    return () => { live = false; clearTimeout(t); };
  }, [offersKey, cid]); // eslint-disable-line react-hooks/exhaustive-deps
  // Only the picked campaign's offers and weeks, and its crop's rival quotes.
  const view = state ? { ...state, offers: inCampaign(state, state.offers, cid), forecast: inCampaign(state, state.forecast, cid), rival_quotes: forCrop(state.rival_quotes, crop) } : null;
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
  // Offers whose confirmation call is happening now: their Undo is locked until the call ends.
  const confirming = new Set(state.calls.filter((c) => c.kind === "confirm" && c.status === "on_call").map((c) => c.offer_id));
  const anyOut = offers.some((o) => o.status === "escalated");
  const rowOf = Object.fromEntries(view.forecast.map((r) => [r.week, r]));
  // Offers keep their calendar week, so after the weeks roll forward they still find the right row.
  const rowByStart = Object.fromEntries(view.forecast.map((r) => [r.week_start, r]));
  const rowFor = (o) => rowByStart[o.deliver_week_start] || rowOf[o.deliver_week];
  // The cheapest supplier quote for the offer's week, to compare its price with (not for offers made from a quote).
  const quoteFor = (o) => (o.source || "").startsWith("rival_quote") ? null
    : view.rival_quotes.filter((q) => q.deliver_week === o.deliver_week).sort((a, b) => a.price_per_kg - b.price_per_kg)[0] || null;
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
    // Keep going when one fails: count both, and undo only what was approved.
    const done = [];
    let failed = 0, firstError = "";
    await act(async () => {
      for (const id of ids) {
        try { await api(`/api/offers/${id}/approve`); done.push(id); } catch (err) {
          if (err.status === 401) throw err;
          failed += 1; firstError = firstError || err.message;
        }
      }
      if (!done.length) throw new Error(`None of the ${ids.length} offers could be approved: ${firstError}`);
    },
      () => failed
        ? `Approved ${done.length} of ${ids.length}. ${failed} failed: ${firstError}`
        : `${ids.length} offers approved. Confirmation calls are queued.`,
      { fn: async () => {
        // An offer whose confirmation call already started cannot be undone; undo the rest and say how many stayed.
        let locked = 0;
        for (const id of done) { try { await api(`/api/offers/${id}/undo`); } catch { locked += 1; } }
        if (locked) throw new Error(`${locked} of ${done.length} could not be undone: the confirmation call has started or finished.`);
      }, ok: "Back to pending." });
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
          {toDecide.length > 0 && impactFailed && <p className="small muted">The impact numbers (weeks, cost, new gaps) are unavailable right now, so they are not shown. Try again.</p>}
          <AnimatePresence initial={false}>
          {toDecide.map((o) => <Offer key={o.id} o={o} l={limits[o.crop]} row={rowFor(o)} quote={quoteFor(o)} imp={impact?.offers?.[o.id]} />)}
          </AnimatePresence>
          {quotes.length > 0 && group("Rival quotes not used yet", quotes.length)}
          <AnimatePresence initial={false}>
          {quotes.map((q) => (
            <motion.div layout className="offer" key={q.id} exit={{ opacity: 0 }} transition={{ duration: 0.25 }}>
              <div className="who"><Avatar name={q.supplier_name} cls="ink" /><div><b>{q.supplier_name}</b><span>Logged quote for week {q.deliver_week}, not used yet</span></div></div>
              <div className="fig"><span>Volume</span><b className="num">{(q.kg / 1000).toFixed(1)} t</b></div>
              <div className="fig"><span>Price, {q.currency || "IDR"}/kg</span><b className="num">{plainPrice(q.price_per_kg, q.currency || "IDR")}</b></div>
              <div className="acts"><ActButton need="offers.decide" busy="Adding…" run={() => act(() => api(`/api/rival-quotes/${q.id}/offer`, { body: { campaign_id: cid } }), "Rival quote added as a pending offer.")}>Add as offer</ActButton></div>
            </motion.div>
          ))}
          </AnimatePresence>
          {decided.length > 0 && group("Decided", decided.length)}
          <AnimatePresence initial={false}>
          {decided.map((o) => <Offer key={o.id} o={o} l={limits[o.crop]} row={rowFor(o)} confirming={confirming.has(o.id)} />)}
          </AnimatePresence>
          {!offers.length && !quotes.length && (
            <div className="empty">
              {gap ? (
                <>
                  <p>No offers yet. Week {gap.week} is {(gap.gap_kg / 1000).toFixed(0)} t short: gap-fill calls ask farmers to move harvest into it, and every deal they agree lands here.</p>
                  <ActButton need="campaign.run" className="btn solid" busy="Queuing calls…"
                    run={() => act(() => api(startUrl(cid), { body: gapFillBody(state) }), gapFillToast)}>
                    <Icon name="phone" size={16} />Start gap-fill calls
                  </ActButton>
                </>
              ) : (
                <>
                  <p>No offers yet, and no week is short right now. Offers appear here when the agent agrees them on gap-fill calls.</p>
                  <Link className="btn" to="/forecast">Go to the live forecast</Link>
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
      <div className="col-side">
        <Meter state={view} week={week} offers={view.offers} />
        {impact && (impact.approved_premium > 0 || impact.all_pending.new_gaps.length > 0) && (
          <section className="card impact-summary" aria-label="Cost of the gap fill">
            {impact.approved_premium > 0 && <p>Of the approved value, <b>Rp {impact.approved_premium.toLocaleString("en-US")}</b> is above the market price: the cost of filling the gap early.</p>}
            {impact.all_pending.new_gaps.length > 0 && <p className="warn">Approving every waiting offer would open a gap in {impact.all_pending.new_gaps.join(" and ")}.</p>}
          </section>
        )}
        <Messages state={state} />
      </div>
      </div>
    </Shell>
  );
}
