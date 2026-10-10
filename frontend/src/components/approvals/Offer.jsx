import { motion } from "motion/react";
import { api, plainPrice } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { Avatar, Pill } from "../../ui.jsx";
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

export default function Offer({ o, l }) {
  const act = useAct();
  // An escalated offer is approved at the farmer's requested price, so that is what must fit.
  const price = o.status === "escalated" && o.requested_price != null ? o.requested_price : o.price_per_kg;
  const inLimits = l && price >= l.floor_price && price <= l.ceiling_price;
  const cur = o.currency || "IDR";
  const open = o.status === "pending" || o.status === "escalated";
  const confirmed = o.status === "approved" && o.confirmed_by_voice;
  return (
    // layout: when a decision re-sorts the list, the row slides to its new place.
    <motion.div layout transition={{ duration: 0.3, ease: "easeOut" }} className={`offer is-${o.status}`}>
      <div className="who"><Avatar name={o.farmer_name} cls={o.kind === "supplier" ? "ink" : ""} /><div><b>{o.farmer_name}</b><span>{detail(o)}</span></div></div>
      <div className="fig"><span>Volume</span><b className="num">{(o.kg / 1000).toFixed(1)} t</b></div>
      <div className="fig"><span>Price, {cur}/kg</span><b className="num">{plainPrice(o.price_per_kg, cur)}</b>{l && <PriceSpot price={price} l={l} cur={cur} />}</div>
      <div className="acts">
        {open ? (
          <>
            {o.status === "pending" ? <Pill cls="amber">Pending</Pill> : <Pill cls="danger">Needs planner</Pill>}
            <button className="btn" onClick={() => act(() => api(`/api/offers/${o.id}/reject`), `Rejected. ${o.farmer_name} will not be confirmed.`, { fn: () => api(`/api/offers/${o.id}/undo`), ok: "Back to pending." })}>Reject</button>
            <button className="btn leaf" disabled={!inLimits} title={inLimits ? undefined : "Outside the current floor and ceiling"}
              onClick={() => act(() => api(`/api/offers/${o.id}/approve`), `Approved. A confirmation call to ${o.farmer_name} is queued.`, { fn: () => api(`/api/offers/${o.id}/undo`), ok: "Back to pending." })}>Approve</button>
          </>
        ) : (
          <>
            <Pill cls={o.status === "approved" ? "mint" : ""}>{confirmed ? "Approved · confirmed by voice" : o.status === "approved" ? "Approved" : "Rejected"}</Pill>
            {!confirmed && <button className="btn ghost" onClick={() => act(() => api(`/api/offers/${o.id}/undo`), "Back to pending.")}>Undo</button>}
          </>
        )}
      </div>
      {o.status === "escalated" && !inLimits && (
        <p className="warn">Above the ceiling of {plainPrice(l ? l.ceiling_price : 0, cur)}. Raise the ceiling on the Setup page to approve, or reject.</p>
      )}
    </motion.div>
  );
}
