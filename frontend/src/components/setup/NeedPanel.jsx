import { Link, useNavigate } from "react-router-dom";
import { forCrop, inCampaign } from "../../campaigns.jsx";
import { toCallOf } from "../../crm.js";
import { api, fmtT, gapFillBody, gapFillToast, startUrl } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton, Icon } from "../../ui.jsx";
import TargetBreakdown from "../forecast/TargetBreakdown.jsx";

// Who needs a harvest call (crm.js: no answer, unsure, date passed, marked), who the forecast has nothing current
// from, and how much those usually bring: the supply the forecast is still guessing about.
export const unknownSupply = (state, cid) => toCallOf(state, cid);

// What the mill needs from this campaign right now, from the live forecast, and what each kind of call does about it:
// harvest calls turn unknown supply into numbers, gap-fill calls cover a short week, a week over capacity needs
// farmers to deliver later.
// The farmers behind one part of a week's bar: the ones whose harvest (or a projected later round) falls in it, the
// ones with an offer waiting for it, the ones not answered yet, or the ones who could bring harvest forward into it.
function farmersBehind(state, cid, d, part, unknown) {
  const start = d.week_start;
  const endDate = new Date(`${start}T00:00:00Z`); endDate.setUTCDate(endDate.getUTCDate() + 6);
  const end = endDate.toISOString().slice(0, 10);
  const members = new Set(inCampaign(state, state.farmers, cid).map((f) => f.id));
  let ids = [];
  let label = "";
  if (part === "there") {
    for (const h of state.harvests) {
      if (!members.has(h.farmer_id)) continue;
      let r = h.ready_date;
      const every = h.every_days;
      while (r && r < start && every >= 5) { const x = new Date(`${r}T00:00:00Z`); x.setUTCDate(x.getUTCDate() + every); r = x.toISOString().slice(0, 10); }
      if (r >= start && r <= end) ids.push(h.farmer_id);
    }
    ids.push(...state.offers.filter((o) => o.status === "approved" && o.deliver_week_start === start && members.has(o.farmer_id)).map((o) => o.farmer_id));
    label = `farmers delivering in ${d.label}`;
  } else if (part === "waiting") {
    ids = state.offers.filter((o) => ["pending", "escalated"].includes(o.status) && o.deliver_week_start === start).map((o) => o.farmer_id);
    label = `farmers with an offer waiting for ${d.label}`;
  } else if (part === "unknown") {
    ids = unknown.map((f) => f.id);
    label = "farmers with no current harvest answer (the unknown part)";
  } else {
    ids = (d.shortlist || []).map((p) => p.farmer_id);
    label = ids.length ? `farmers who could bring harvest forward into ${d.label}` : `farmers for ${d.label}: none can bring harvest forward; log a supplier quote`;
  }
  return { ids: new Set(ids), label };
}

export default function NeedPanel({ state, cid, campaign, onPick }) {
  const act = useAct();
  const navigate = useNavigate();
  const rows = inCampaign(state, state.forecast, cid).sort((a, b) => a.week - b.week);
  if (!rows.length) return null;
  const gap = rows.find((r) => r.is_gap);
  const over = rows.find((r) => r.is_surplus);
  const { toCall, unknown, usualKg } = unknownSupply(state, cid);
  const running = campaign.status === "running";
  const quotes = gap ? forCrop(state.rival_quotes, campaign.crop).filter((q) => q.deliver_week === gap.week) : [];
  const forwardKg = gap ? (gap.shortlist || []).reduce((n, p) => n + (p.kg || 0), 0) : 0;
  const quoteKg = quotes.reduce((n, q) => n + q.kg, 0);
  const cover = gap ? Math.min(100, Math.round(((forwardKg + quoteKg) / Math.max(gap.gap_kg, 1)) * 100)) : 0;
  const startCollect = async () => {
    const r = await act(() => api(startUrl(cid), { body: { kind: "collect", channel: state.settings?.phone_calls ? "twilio" : "browser" } }),
      (x) => `${x.queued} harvest calls started.`);
    if (r) navigate(state.settings?.phone_calls ? "/" : "/calls");
  };
  const status = gap ? `Week ${gap.week} is ${fmtT(gap.gap_kg)} t short` : over ? `Week ${over.week} is ${fmtT(over.surplus_kg)} t over capacity` : "Every week is on track";
  return (
    <section className="card need" id="need" aria-labelledby="need-title">
      <div className="card-head">
        <div>
          <h2 id="need-title">What the mill needs</h2>
          <span className={`need-status ${gap ? "short" : over ? "over" : "ok"}`}>{status}</span>
        </div>
        <Link className="btn sm" to="/">See the forecast</Link>
      </div>
      <TargetBreakdown rows={rows} unknownKg={usualKg} compact onPick={onPick ? (d, part) => onPick(farmersBehind(state, cid, d, part, unknown)) : undefined} />
      <ol className="need-actions">
        <li className={unknown.length ? "todo" : "done"}>
          <span className="na-icon"><Icon name="phone" size={16} /></span>
          <div>
            <b>Get harvest answers</b>
            <p>{toCall.length
              ? <>{toCall.length} farmers need a harvest call{unknown.length ? <>: {unknown.length} have no current answer (they usually bring about <b>{fmtT(usualKg)} t a week</b>, which the forecast cannot count yet)</> : ""}{toCall.length - unknown.length ? `${unknown.length ? ", and " : ": "}${toCall.length - unknown.length} gave an unsure answer or are marked to call` : ""}.</>
              : <>Every farmer has a firm, current harvest answer. Nobody needs a harvest call now.</>}</p>
          </div>
          {!running && toCall.length > 0 && <ActButton need="campaign.run" className="btn sm" busy="Starting…" run={startCollect}>Call {toCall.length} farmers</ActButton>}
        </li>
        <li className={gap ? "todo" : "done"}>
          <span className="na-icon"><Icon name="approvals" size={16} /></span>
          <div>
            <b>{gap ? `Fill week ${gap.week}` : "No short week"}</b>
            <p>{gap
              ? <>{fmtT(gap.gap_kg)} t short{usualKg && !gap.before_start ? `; up to ${fmtT(Math.min(usualKg, gap.gap_kg))} t of it may come once the farmers answer, the rest needs to be added` : ""}. {gap.shortlist?.length ? `${gap.shortlist.length} farmers could bring about ${fmtT(forwardKg)} t forward` : "No farmer on record can bring harvest forward"}{quoteKg ? `, and a rival quote offers ${fmtT(quoteKg)} t` : ""}: about <b>{cover}%</b> of the gap. The agent offers a better price, inside your range; you approve each deal.{cover < 100 ? " For the rest, log a quote from another supplier (Approvals) or add farmers who can harvest earlier." : ""}</>
              : <>Every week is within the target. Gap-fill calls are not needed now.</>}</p>
          </div>
          {gap && !running && (gap.shortlist?.length || quoteKg) ? <ActButton need="campaign.run" className="btn sm solid" busy="Queuing…" run={() => act(() => api(startUrl(cid), { body: gapFillBody(state) }), gapFillToast)}>Start gap-fill calls</ActButton> : null}
        </li>
        {over && (
          <li className="todo over">
            <span className="na-icon"><Icon name="calendar" size={16} /></span>
            <div>
              <b>Spread week {over.week}</b>
              <p>{fmtT(over.expected_kg)} t expected, the mill presses {fmtT(over.capacity_kg)} t. Ask some farmers to harvest a week later so the fruit does not wait and spoil.</p>
            </div>
            <Link className="btn sm" to="/">Choose farmers</Link>
          </li>
        )}
      </ol>
    </section>
  );
}
