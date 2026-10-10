import { fmtT } from "../../lib.js";

// The week's gap before any approval, and how much approved offers have closed.
export default function Meter({ state, week }) {
  const row = state.forecast.find((r) => r.week === week);
  if (!row) return null;
  const closed = row.approved_in_kg || 0;
  const original = Math.max(row.target_kg - (row.expected_kg - closed), 0);
  const remaining = Math.max(original - closed, 0);
  const share = original ? Math.min(closed / original, 1) : 1;
  const awaiting = state.calls.filter((c) => c.kind === "confirm" && c.status === "queued").length;
  return (
    <section className="card" id="meter-card" aria-labelledby="meter-title" aria-live="polite">
      <div className="card-head" style={{ alignItems: "baseline" }}>
        <h2 id="meter-title">Gap meter</h2>
        <span style={{ fontSize: 16 }}>
          <strong>{(closed / 1000).toFixed(1)} t</strong> of {(original / 1000).toFixed(1)} t closed · <strong>{(remaining / 1000).toFixed(1)} t</strong> still short
        </span>
      </div>
      <div className="meter" role="progressbar" aria-labelledby="meter-title" aria-valuenow={Math.round(share * 100)}><i style={{ width: `${share * 100}%` }} /></div>
      {remaining < 50 && original > 0 ? (
        <div className="meter-done">
          <span>Week {week} gap closed. {awaiting ? "Confirmation calls are ready to go out." : "Confirmations are done."}</span>
          <a className="btn leaf" href="/call.html" target="_blank" rel="noopener">Hear a confirmation call</a>
        </div>
      ) : !row.is_gap && closed > 0 ? (
        <p className="sub">Week {week} is no longer flagged as a gap. {fmtT(remaining)} t is still below the target.</p>
      ) : null}
    </section>
  );
}
