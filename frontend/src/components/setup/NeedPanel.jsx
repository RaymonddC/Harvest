import { Link, useNavigate } from "react-router-dom";
import { forCrop, inCampaign } from "../../campaigns.jsx";
import { api, fmtT, gapFillBody, gapFillToast, startUrl } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton, Icon } from "../../ui.jsx";
import TargetBreakdown from "../forecast/TargetBreakdown.jsx";

// Who in the campaign has not told us their next harvest yet (no harvest on record from week 1 on), and how much
// they usually bring: the supply the forecast is still guessing about.
export function unknownSupply(state, cid) {
  const start = state.settings?.plan_start || "";
  const known = new Set(state.harvests.filter((h) => (h.ready_date || "") >= start).map((h) => h.farmer_id));
  const toCall = inCampaign(state, state.farmers, cid).filter((f) => f.to_call && f.type !== "supplier" && !f.do_not_call);
  const unknown = toCall.filter((f) => !known.has(f.id));
  return { toCall, unknown, usualKg: unknown.reduce((n, f) => n + (f.usual_kg_week || 0), 0) };
}

// What the mill needs from this campaign right now, from the live forecast, and what each kind of call does about it:
// harvest calls turn unknown supply into numbers, gap-fill calls cover a short week, a week over capacity needs
// farmers to deliver later.
export default function NeedPanel({ state, cid, campaign }) {
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
      <TargetBreakdown rows={rows} unknownKg={usualKg} compact />
      <ol className="need-actions">
        <li className={unknown.length ? "todo" : "done"}>
          <span className="na-icon"><Icon name="phone" size={16} /></span>
          <div>
            <b>Get harvest answers</b>
            <p>{unknown.length
              ? <>{unknown.length} of the {toCall.length} farmers to call have not said what they will harvest. They usually bring about <b>{fmtT(usualKg)} t a week</b>; the forecast cannot count it until they answer.</>
              : toCall.length ? <>All {toCall.length} farmers to call have given their next harvest. Call again to refresh the numbers.</>
              : <>No farmers to call in this campaign yet. Add them above.</>}</p>
          </div>
          {!running && toCall.length > 0 && <ActButton need="campaign.run" className="btn sm" busy="Starting…" run={startCollect}>{unknown.length ? `Call ${toCall.length} farmers` : "Call again"}</ActButton>}
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
