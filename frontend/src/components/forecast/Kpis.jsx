import { fmtT } from "../../lib.js";

// A figure, a line of context under it, and (optionally) a bar showing how far it has got.
const Kpi = ({ label, cls = "", value, note, share }) => (
  <div className={`kpi ${cls}`}>
    <span className="label">{label}</span>
    <span className="value">{value}</span>
    {share !== undefined && <div className="bar" aria-hidden="true"><i style={{ width: `${Math.min(Math.max(share, 0), 1) * 100}%` }} /></div>}
    {note && <span className="kpi-note">{note}</span>}
  </div>
);

// The gap itself is the banner above; these are the supporting figures.
export default function Kpis({ rows, calls, toCall }) {
  if (!rows.length) return <div className="kpis" id="kpis" />;
  const target = rows[0].target_kg;
  const gap = rows.find((r) => r.is_gap);
  const focus = gap || rows.reduce((a, b) => (b.expected_kg < a.expected_kg ? b : a));
  const done = calls.filter((c) => ["done", "declined"].includes(c.status)).length;
  const onTrack = rows.filter((r) => !r.is_gap).length;
  return (
    <div className="kpis" id="kpis" aria-live="polite">
      <Kpi label="Weekly target" value={`${fmtT(target)} t`} note={`${onTrack} of ${rows.length} weeks on track`} share={onTrack / rows.length} />
      <Kpi label={`Week ${focus.week} expected`} value={`${fmtT(focus.expected_kg)} t`}
        note={`${Math.round((focus.expected_kg / target) * 100)}% of the target`} share={focus.expected_kg / target} />
      {calls.length
        ? <Kpi label="Calls" value={<span>{done} <small>of {calls.length} done</small></span>} share={done / calls.length}
          note={calls.length - done ? `${calls.length - done} still to go` : "Every farmer answered"} />
        : <Kpi label="Calls" value={toCall ? `${toCall} ready` : "None yet"} note={toCall ? "Start calling on the Setup page" : "Add farmers on the Setup page"} />}
    </div>
  );
}
