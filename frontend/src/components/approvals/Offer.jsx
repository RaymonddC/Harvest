import { motion } from "motion/react";
import { api, plainPrice } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton, Avatar, Pill } from "../../ui.jsx";
import PriceSpot from "./PriceSpot.jsx";

function detail(o) {
  const n = o.negotiation || {};
  const cur = o.currency || "IDR";
  const parts = [];
  if (o.village && o.kind !== "supplier") parts.push(o.village);
  if (n.rival_quote) parts.push("Logged rival quote, used after farmers");
  else if (o.status === "escalated" || n.escalated) parts.push(`Asked ${plainPrice(o.requested_price, cur)}, above the ceiling`);
  else if (n.counter && n.first_offer && n.counter > n.first_offer) parts.push(`Countered from ${plainPrice(n.first_offer, cur)}, accepted inside the ceiling`);
  else if (n.counter && n.first_offer && n.counter < n.first_offer) parts.push("Asked less than our offer; paid at least the floor");
  else if (n.rung > 0) parts.push(`Accepted step ${n.rung + 1} of the offer ladder`);
  else parts.push("Accepted the first offer");
  if (o.from_week) parts.push(`moves delivery from week ${o.from_week}`);
  return parts.join(" · ");
}

// What approving this offer does to the week it delivers in, from that week's shortfall today.
function impact(o, row) {
  if (!row || !o.deliver_week) return null;
  const t = (kg) => `${(kg / 1000).toFixed(kg >= 10000 ? 0 : 1)} t`;
  if (!row.gap_kg) return { cls: "", text: `Week ${o.deliver_week} already meets its target` };
  const left = row.gap_kg - o.kg;
  return left <= 0 ? { cls: "closes", text: `Closes the week ${o.deliver_week} gap` }
    : { cls: "", text: `+${t(o.kg)} to week ${o.deliver_week}, still ${t(left)} short` };
}

// confirming: the confirmation call to this farmer is in progress, so the decision is locked.
// The price next to what a planner would check it against: the market price the agent started
// from, a supplier's quote for the same week, and the room left under the ceiling.
function proof(o, l, quote, price) {
  const cur = o.currency || "IDR";
  const out = [];
  const ref = o.reference_price || l?.reference_price;
  if (ref) {
    const pct = (price / ref - 1) * 100;
    out.push({ k: "market", text: `${pct >= 0 ? "+" : "−"}${Math.abs(pct).toFixed(1)}% vs market ${plainPrice(ref, cur)}` });
  }
  if (quote) {
    const d = price - quote.price_per_kg;
    out.push({ k: "rival", text: Math.abs(d) < 0.5 ? `Same as ${quote.supplier_name}'s quote`
      : `${plainPrice(Math.abs(d), cur)} ${d > 0 ? "more" : "less"} than ${quote.supplier_name}'s quote` });
  }
  if (l) {
    const room = l.ceiling_price - price;
    out.push({ k: room < 0 ? "over" : "room", text: room < 0 ? `${plainPrice(-room, cur)} over the ceiling` : `${plainPrice(room, cur)} under the ceiling` });
  }
  return out;
}

const money = (n, cur) => (cur === "IDR" ? `Rp ${Math.round(n).toLocaleString("en-US")}` : `${n.toLocaleString("en-US", { maximumFractionDigits: 2 })} ${cur}`);
const TEXT_WORD = { sent: "Text sent", failed: "Text failed", not_sent: "Text not sent" };

// imp: what approving this offer alone does to every week (from /api/approvals/impact), and its cost.
export default function Offer({ o, l, row, quote, confirming = false, imp = null }) {
  const act = useAct();
  // An escalated offer is approved at the farmer's requested price, so that is what must fit.
  const price = o.status === "escalated" && o.requested_price != null ? o.requested_price : o.price_per_kg;
  const inLimits = l && price >= l.floor_price && price <= l.ceiling_price;
  const cur = o.currency || "IDR";
  const open = o.status === "pending" || o.status === "escalated";
  const confirmed = o.status === "approved" && o.confirmed_by_voice;
  const effect = open ? impact(o, row) : null;
  const checks = open ? proof(o, l, quote, price) : [];
  return (
    // layout: when a decision re-sorts the list, the row slides to its new place.
    <motion.div layout transition={{ duration: 0.3, ease: "easeOut" }} className={`offer is-${o.status}`}>
      <div className="who"><Avatar name={o.farmer_name} cls={o.kind === "supplier" ? "ink" : ""} /><div><b>{o.farmer_name}</b><span>{detail(o)}</span>{effect && <span className={`impact ${effect.cls}`}>{effect.text}</span>}</div></div>
      <div className="fig"><span>Volume</span><b className="num">{(o.kg / 1000).toFixed(1)} t</b></div>
      <div className="fig"><span>Price, {cur}/kg</span><b className="num">{plainPrice(o.price_per_kg, cur)}</b>{l && <PriceSpot price={price} l={l} cur={cur} market={o.reference_price || l.reference_price} rival={quote?.price_per_kg} />}</div>
      <div className="acts">
        {open ? (
          <>
            {o.status === "pending" ? <Pill cls="amber">Pending</Pill> : <Pill cls="danger">Needs planner</Pill>}
            <ActButton need="offers.decide" busy="Rejecting…" run={() => act(() => api(`/api/offers/${o.id}/reject`), `Rejected. ${o.farmer_name} will not be confirmed.`, { fn: () => api(`/api/offers/${o.id}/undo`), ok: "Back to pending." })}>Reject</ActButton>
            <ActButton need="offers.decide" className="btn leaf" busy="Approving…" disabled={!inLimits} title={inLimits ? undefined : "Outside the current floor and ceiling"}
              run={() => act(() => api(`/api/offers/${o.id}/approve`), `Approved. A confirmation call to ${o.farmer_name} is queued.`, { fn: () => api(`/api/offers/${o.id}/undo`), ok: "Back to pending." })}>Approve</ActButton>
          </>
        ) : (
          <>
            <Pill cls={o.status === "approved" ? "mint" : ""}>{confirmed ? "Approved · confirmed by voice" : confirming ? "Approved · calling now" : o.status === "approved" ? "Approved" : "Rejected"}</Pill>
            {!confirmed && <ActButton need="offers.decide" className="btn ghost" busy="Undoing…" disabled={confirming} title={confirming ? "The confirmation call is in progress. Undo is available again if it ends without a confirmation." : undefined}
              run={() => act(() => api(`/api/offers/${o.id}/undo`), "Back to pending.")}>Undo</ActButton>}
          </>
        )}
      </div>
      {open && imp && (
        <div className="impact-box">
          {imp.weeks.length > 0 && (
            <p className="impact-weeks"><b>If approved:</b>{" "}
              {imp.weeks.map((w) => <span key={w.label} className={w.is_gap && !w.was_gap ? "turns-gap" : w.was_gap && !w.is_gap ? "closes" : ""}>
                {w.label} {(w.before_kg / 1000).toFixed(1)} → {(w.after_kg / 1000).toFixed(1)} t</span>)}
            </p>
          )}
          <p className="impact-cost">Costs {money(imp.cost, imp.currency)}{imp.premium > 0 ? `, ${money(imp.premium, imp.currency)} over the market price` : ""}.</p>
          {imp.new_gaps.length > 0 && <p className="warn">Approving opens a gap in {imp.new_gaps.join(" and ")}: that week drops below the threshold.</p>}
        </div>
      )}
      {o.status === "approved" && (
        <div className="text-line">
          <span className="small muted">{o.text_status ? TEXT_WORD[o.text_status] || o.text_status : "No written confirmation yet"}{o.text_status === "not_sent" ? " (see Messages)" : ""}</span>
          <ActButton need="offers.decide" className="btn sm ghost" busy="Sending…"
            run={() => act(() => api(`/api/offers/${o.id}/send-confirmation`), (m) => (m && m.status === "sent" ? "Text sent to the farmer." : `Recorded, not sent: ${m?.reason || ""}`))}>
            {o.text_status ? "Send text again" : "Send text"}</ActButton>
        </div>
      )}
      {checks.length > 0 && (
        <ul className="proof" aria-label="Price check">
          {checks.map((x) => <li key={x.k} className={x.k}><i aria-hidden="true" />{x.text}</li>)}
        </ul>
      )}
      {o.status === "escalated" && !inLimits && (
        <p className="warn">Above the ceiling of {plainPrice(l ? l.ceiling_price : 0, cur)}. Raise the ceiling on the Campaign page to approve, or reject.</p>
      )}
    </motion.div>
  );
}
