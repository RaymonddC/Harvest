import { fmtT, plainPrice } from "../../lib.js";

const Stat = ({ label, children, cls = "" }) => <div className={`ws-stat ${cls}`}><span>{label}</span><b className="num">{children}</b></div>;

// The week this page is about: how much of its gap approved offers have closed, what is still
// waiting, and what the approved deals cost.
export default function Meter({ state, week, offers }) {
  const row = state.forecast.find((r) => r.week === week);
  if (!row) return null;
  const closed = row.approved_in_kg || 0;
  const original = Math.max(row.target_kg - (row.expected_kg - closed), 0);
  const remaining = Math.max(original - closed, 0);
  const share = original ? Math.min(closed / original, 1) : 1;
  const awaiting = state.calls.filter((c) => c.kind === "confirm" && c.status === "queued").length;
  const inWeek = offers.filter((o) => o.deliver_week === week);
  const sum = (list) => list.reduce((s, o) => s + o.kg, 0);
  const waiting = inWeek.filter((o) => o.status === "pending" || o.status === "escalated");
  const approved = inWeek.filter((o) => o.status === "approved");
  const value = approved.reduce((s, o) => s + o.kg * o.price_per_kg, 0);
  const cur = approved[0]?.currency || "IDR";

  return (
    <section className="card week-summary" id="meter-card" aria-labelledby="meter-title" aria-live="polite">
      <h2 id="meter-title">Week {week} gap</h2>
      <div className="ws-big">
        <b className="num">{fmtT(closed)}</b><span>of {fmtT(original)} t closed</span>
      </div>
      <div className="meter big" role="progressbar" aria-labelledby="meter-title" aria-valuenow={Math.round(share * 100)}><i style={{ width: `${share * 100}%` }} /></div>
      <p className={`ws-left ${remaining < 50 ? "done" : ""}`}>{remaining < 50 ? "Gap closed" : `${fmtT(remaining)} t still short`}</p>
      <div className="ws-stats">
        <Stat label="Waiting for you" cls={waiting.length ? "amber" : ""}>{waiting.length ? `${waiting.length} · ${fmtT(sum(waiting))} t` : "None"}</Stat>
        <Stat label="Approved">{approved.length ? `${approved.length} · ${fmtT(sum(approved))} t` : "None"}</Stat>
        <Stat label="Approved value">{approved.length ? `${cur === "IDR" ? "Rp " : ""}${plainPrice(value, cur)}` : "–"}</Stat>
      </div>
      {remaining < 50 && original > 0 ? (
        <div className="meter-done">
          <span>{awaiting ? "Confirmation calls are ready to go out." : "Confirmations are done."}</span>
          <a className="btn leaf" href="/call.html" target="_blank" rel="noopener">Hear a confirmation call</a>
        </div>
      ) : !row.is_gap && closed > 0 ? (
        <p className="sub">Week {week} is no longer flagged as a gap. {fmtT(remaining)} t is still below the target.</p>
      ) : null}
    </section>
  );
}
