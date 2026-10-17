import { useState } from "react";
import { Link } from "react-router-dom";
import { fmtT } from "../../lib.js";

const span = (ws) => {
  const a = new Date(`${ws}T00:00:00`); const b = new Date(a); b.setDate(b.getDate() + 6);
  const f = (d, m) => d.toLocaleDateString("en-GB", m ? { day: "numeric", month: "short" } : { day: "numeric" });
  return a.getMonth() === b.getMonth() ? `${f(a)}–${f(b, true)}` : `${f(a, true)} – ${f(b, true)}`;
};

// Where each week's target stands, as one stacked bar per week (part of a whole):
//   Already there    answers saved (firm, unsure at half, projected rounds) and approved deals
//   Waiting for you  offers the agent made that wait for approval
//   Not answered yet what the farmers who have not given their harvest usually bring (an estimate)
//   Still to add     the rest of the target: gap-fill calls or another supplier
// Every bar is drawn on the same scale (the target or the biggest week), so weeks compare; tonnes over the target
// show past the target line. Hover or focus a bar for its numbers; "Show as table" lists them all.
const PARTS = [
  { key: "there", label: "Already there", cls: "tb-there" },
  { key: "waiting", label: "Waiting for your approval", cls: "tb-waiting" },
  { key: "unknown", label: "Not answered yet (usual supply)", cls: "tb-unknown" },
  { key: "missing", label: "Still to add", cls: "tb-missing" },
];

export function breakdown(rows, unknownKg) {
  return rows.map((r) => {
    const there = r.expected_kg;
    const waiting = r.pending_kg || 0;
    const unknown = r.before_start ? 0 : unknownKg;
    const missing = Math.max(r.target_kg - there - waiting - unknown, 0);
    return { ...r, there, waiting, unknown, missing, over: Math.max(there - r.target_kg, 0) };
  });
}

export default function TargetBreakdown({ rows, unknownKg, compact = false, onPick }) {
  const [table, setTable] = useState(false);
  const [hover, setHover] = useState(null);
  const data = breakdown(rows, unknownKg);
  if (!data.length) return null;
  const max = Math.max(...data.map((d) => Math.max(d.target_kg, d.there + d.waiting + d.unknown)), 1);
  const pct = (kg) => `${(kg / max) * 100}%`;
  // The headline week: the first the forecast calls short, else the first that still needs tonnes, else week 1.
  const focus = data.find((d) => d.is_gap) || data.find((d) => d.missing > 0 && !d.before_start) || data[0];
  return (
    <div className={`tbd ${compact ? "compact" : ""}`}>
      {!compact && (
        <p className="tbd-say" aria-live="polite">
          {focus.missing
            ? <>Week {focus.week} ({span(focus.week_start)}) still needs <b>{fmtT(focus.missing)} t</b>: {fmtT(focus.there)} t is there{focus.waiting ? `, ${fmtT(focus.waiting)} t waits for your approval` : ""}{focus.unknown ? `, and about ${fmtT(focus.unknown)} t should come from farmers who have not answered` : ""}.</>
            : <>Every week is covered once the farmers answer.</>}
        </p>
      )}
      <div className="tbd-legend small" aria-hidden="true">
        {PARTS.map((p) => <span key={p.key}><i className={p.cls} />{p.label}</span>)}
        <span><i className="tb-target" />Target</span>
      </div>
      {table ? (
        <div className="table-wrap">
          <table className="tbd-table">
            <thead><tr><th>Week</th><th className="r">Target</th>{PARTS.map((p) => <th key={p.key} className="r">{p.label}</th>)}</tr></thead>
            <tbody>
              {data.map((d) => (
                <tr key={d.id}><td>{d.label}{d.before_start ? " (not started)" : ""}</td><td className="r num">{fmtT(d.target_kg)} t</td>
                  {PARTS.map((p) => <td key={p.key} className="r num">{fmtT(d[p.key])} t</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ul className="tbd-rows">
          {data.map((d) => (
            <li key={d.id} className={`${d.before_start ? "before" : ""} ${hover === d.id ? "on" : ""}`}
              tabIndex={0} onMouseEnter={() => setHover(d.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(d.id)} onBlur={() => setHover(null)}
              aria-label={`${d.label}: ${fmtT(d.there)} t there, ${fmtT(d.waiting)} t waiting, ${fmtT(d.unknown)} t not answered, ${fmtT(d.missing)} t still to add, target ${fmtT(d.target_kg)} t`}>
              <span className="tbd-label"><b>{d.label} <span className="tbd-dates">{span(d.week_start)}</span></b><small>{d.before_start ? "not started" : d.missing ? `${fmtT(d.missing)} t to add` : d.over ? `${fmtT(d.over)} t over` : d.there >= d.target_kg ? "covered" : "covered once farmers answer"}</small></span>
              <div className="tbd-track">
                <div className="tbd-bar">
                  {PARTS.map((p) => d[p.key] > 0 && (onPick
                    ? <button key={p.key} type="button" className={`seg-btn ${p.cls}`} style={{ width: pct(d[p.key]) }} aria-label={`${p.label} in ${d.label}: show the farmers`} onClick={() => onPick(d, p.key)} />
                    : <i key={p.key} className={p.cls} style={{ width: pct(d[p.key]) }} />))}
                </div>
                <i className="tbd-target" style={{ left: pct(d.target_kg) }} />
              </div>
              <Link className="tbd-cal" to={`/calendar?date=${d.week_start}`} aria-label={`${d.label} in the calendar`} title="Open this week in the calendar">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></svg>
              </Link>
              <div className="tbd-tipwrap">
                {hover === d.id && (
                  <div className="tbd-tip" role="tooltip">
                    <b>{d.label}, target {fmtT(d.target_kg)} t</b>
                    {PARTS.map((p) => <span key={p.key}><i className={p.cls} />{p.label}<b>{fmtT(d[p.key])} t</b></span>)}
                    {d.over > 0 && <span className="over">Over the target by {fmtT(d.over)} t</span>}
                    {onPick && <span className="tip-hint">Click a part to see its farmers</span>}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="btn sm ghost tbd-toggle" onClick={() => setTable(!table)}>{table ? "Show as chart" : "Show as table"}</button>
    </div>
  );
}
