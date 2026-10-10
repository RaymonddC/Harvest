import { Link } from "react-router-dom";
import { api, fmtPrice, fmtT } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton, Avatar, Icon, Pill } from "../../ui.jsx";
import { shortDate } from "./Chart.jsx";

// Who can fill the gap: farmers who can bring delivery forward, and logged rival quotes.
function supply(gap, state) {
  const list = gap.shortlist || [];
  const farmersKg = list.reduce((s, p) => s + p.kg, 0);
  const quotes = state.rival_quotes.filter((q) => q.deliver_week === gap.week);
  const quoteKg = quotes.reduce((s, q) => s + q.kg, 0);
  return { list, farmersKg, quotes, quoteKg };
}

// The one thing this page is about, at the top: the gap week (with the way to fill it), or the
// news that every week is on track (and which approved offers closed the gap).
export function Hero({ gap, rows, state }) {
  const act = useAct();
  const target = rows[0].target_kg;
  const waiting = state.offers.filter((o) => ["pending", "escalated"].includes(o.status)).length;
  if (!gap) {
    const approved = state.offers.filter((o) => o.status === "approved" && o.deliver_week);
    const covered = approved.length ? approved[approved.length - 1].deliver_week : null;
    return (
      <section className="hero ok" aria-live="polite">
        <span className="hero-mark"><Icon name="check" size={22} /></span>
        <div className="hero-text">
          <span className="hero-eyebrow">{covered ? "Gap closed" : "No gap"}</span>
          <h2>{covered ? `Week ${covered} is covered` : "Every week is on track"}</h2>
          <p>{covered ? "Approved offers filled the gap. Every week is now within the gap threshold of the target."
            : `Each of the ${rows.length} weeks is within the gap threshold of the ${fmtT(target)} t target.`}</p>
        </div>
        {waiting > 0 && <div className="hero-acts"><Link className="btn" to="/approvals">Review {waiting} waiting</Link></div>}
      </section>
    );
  }
  const { list, farmersKg, quotes, quoteKg } = supply(gap, state);
  const canFill = list.length > 0 || state.farmers.some((f) => f.type === "supplier");
  const campaign = state.campaigns.find((x) => x.id === "current") || {};
  const calling = campaign.status === "running" && campaign.kind === "gap_fill";
  let text = list.length
    ? `${list.length} farmer${list.length > 1 ? "s" : ""} can bring about ${fmtT(farmersKg)} t forward`
    : "No farmer on record can bring delivery forward";
  text += quotes.length ? `, and a rival quote covers ${fmtT(Math.min(quoteKg, Math.max(gap.gap_kg - farmersKg, 0)) || quoteKg)} t.` : ".";
  return (
    <section className="hero gap" aria-live="polite">
      <div className="hero-text">
        <span className="hero-eyebrow">Gap alert · week {gap.week} · from {shortDate(gap.week_start)}</span>
        <h2><span className="num">{fmtT(gap.gap_kg)} t</span> short</h2>
        <p>{fmtT(gap.expected_kg)} of {fmtT(target)} t expected. {text}{calling ? " Gap-fill calls are running now." : ""}</p>
      </div>
      <div className="hero-acts">
        {/* While gap-fill calls run, the next step is answering them, not starting more. */}
        {calling ? <a className="btn solid big" href="/call.html" target="_blank" rel="noopener"><Icon name="phone" size={16} />Open call client</a> : (
        <ActButton className="btn solid big" busy="Queuing calls…" disabled={!canFill}
          run={() => act(() => api("/api/campaign/start", { body: { kind: "gap_fill" } }), (r) => `${r.queued} gap-fill calls queued. Answer them in the call client.`)}>
          <Icon name="phone" size={16} />Start gap-fill calls
        </ActButton>)}
        {waiting > 0 && <Link className="btn" to="/approvals">Review {waiting} waiting</Link>}
      </div>
    </section>
  );
}

// Beside the chart: the farmers and quotes that could fill the gap week.
export function FillList({ gap, state }) {
  const act = useAct();
  const { list, quotes } = supply(gap, state);
  const used = (q) => state.offers.some((o) => o.source === `rival_quote:${q.id}` && ["pending", "approved"].includes(o.status));
  const top = list.slice(0, 4);
  const rest = list.slice(4);
  return (
    <section className="card" aria-labelledby="fill-title">
      <div className="card-head"><h2 id="fill-title">Who can fill week {gap.week}</h2></div>
      {list.length || quotes.length ? (
        <div className="list-card">
          {top.map((p) => (
            <div className="li" key={p.farmer_id || p.name}><Avatar name={p.name} cls="sm" /><span>{p.name}{p.village ? ` · ${p.village}` : ""}</span><strong>{fmtT(p.kg)} t</strong></div>
          ))}
          {rest.length > 0 && (
            <div className="li"><span className="avatar sm grey" aria-hidden="true">+{rest.length}</span>
              <span className="muted">{rest.length} more farmer{rest.length > 1 ? "s" : ""}</span>
              <strong>{fmtT(rest.reduce((s, p) => s + p.kg, 0))} t</strong></div>
          )}
          {quotes.map((q) => (
            <div className="li sep" key={q.id}>
              <Avatar name={q.supplier_name} cls="sm ink" />
              <span>{q.supplier_name}, quote {fmtPrice(q.price_per_kg, q.currency || "IDR")}</span>
              <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {used(q) ? <Pill cls="mint">Offer added</Pill>
                  : <ActButton className="btn sm" busy="Adding…" run={() => act(() => api(`/api/rival-quotes/${q.id}/offer`), "Rival quote added to approvals.")}>Add as offer</ActButton>}
                <strong>{fmtT(q.kg)} t</strong>
              </span>
            </div>
          ))}
        </div>
      ) : <p className="muted">No farmer or supplier on record can fill this week.</p>}
    </section>
  );
}
