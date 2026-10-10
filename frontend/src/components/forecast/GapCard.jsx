import { api, fmtPrice, fmtT } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { Avatar, Icon, Pill } from "../../ui.jsx";

// The gap week: who can bring delivery forward, rival quotes, and the gap-fill button.
export function GapCard({ gap, state }) {
  const act = useAct();
  const list = gap.shortlist || [];
  const farmersKg = list.reduce((s, p) => s + p.kg, 0);
  const fromWeeks = [...new Set(list.map((p) => p.from_week))].sort().map((w) => `week ${w}`).join(" and ");
  const quotes = state.rival_quotes.filter((q) => q.deliver_week === gap.week);
  const quoteKg = quotes.reduce((s, q) => s + q.kg, 0);
  const used = (q) => state.offers.some((o) => o.source === `rival_quote:${q.id}` && ["pending", "approved"].includes(o.status));
  let text = list.length
    ? `${list.length} farmer${list.length > 1 ? "s" : ""} can bring delivery forward from ${fromWeeks}, about ${fmtT(farmersKg)} t.`
    : "No farmer on record can bring delivery forward.";
  if (quotes.length) text += farmersKg + quoteKg >= gap.gap_kg
    ? ` A rival supplier quote covers the remaining ${fmtT(gap.gap_kg - farmersKg > 0 ? gap.gap_kg - farmersKg : quoteKg)} t.`
    : ` A rival supplier quote covers ${fmtT(quoteKg)} t.`;
  const top = list.slice(0, 3);
  const rest = list.slice(3);
  return (
    <section className="card amber" id="gap-card" aria-live="polite">
      <span className="eyebrow">Gap alert · week {gap.week}</span>
      <h2 style={{ fontSize: 22 }}>{fmtT(gap.gap_kg)} t to fill</h2>
      <p>{text}</p>
      {(list.length > 0 || quotes.length > 0) && (
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
                  : <button className="btn sm" onClick={() => act(() => api(`/api/rival-quotes/${q.id}/offer`), "Rival quote added to approvals.")}>Add as offer</button>}
                <strong>{fmtT(q.kg)} t</strong>
              </span>
            </div>
          ))}
        </div>
      )}
      <button className="btn leaf big block" disabled={!list.length && !state.farmers.some((f) => f.type === "supplier")}
        onClick={() => act(() => api("/api/campaign/start", { body: { kind: "gap_fill" } }), (r) => `${r.queued} gap-fill calls queued. Answer them in the call client.`)}>
        <Icon name="phone" size={16} />Start gap-fill calls
      </button>
    </section>
  );
}

// No gap left while approved offers exist: those offers closed it.
export function OkCard({ state }) {
  const approved = state.offers.filter((o) => o.status === "approved" && o.deliver_week);
  const coveredWeek = approved.length ? approved[approved.length - 1].deliver_week : null;
  if (coveredWeek === null) {
    return (
      <section className="card mint" id="ok-card">
        <div className="eyebrow">No gap</div>
        <h2 className="serif" style={{ fontSize: 24 }}>Every week is on track</h2>
        <p>Each week is within the gap threshold of the target.</p>
      </section>
    );
  }
  return (
    <section className="card mint covered" id="ok-card">
      <span className="covered-mark"><Icon name="check" size={22} /></span>
      <div className="eyebrow">Gap closed</div>
      <h2 style={{ fontSize: 22 }}>Week {coveredWeek} is covered</h2>
      <p>Approved offers filled the gap. Every week is now within the gap threshold of the target.</p>
    </section>
  );
}
