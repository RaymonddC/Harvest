import { fmtT } from "../../lib.js";

const Kpi = ({ label, cls = "", children, extra }) => (
  <div className={`kpi ${cls}`}><span className="label">{label}</span><span className="value">{children}</span>{extra}</div>
);

export default function Kpis({ rows, calls }) {
  if (!rows.length) return <div className="kpis" id="kpis" />;
  const target = rows[0].target_kg;
  const gap = rows.find((r) => r.is_gap);
  const focus = gap || rows.reduce((a, b) => (b.expected_kg < a.expected_kg ? b : a));
  const done = calls.filter((c) => ["done", "declined"].includes(c.status)).length;
  return (
    <div className="kpis" id="kpis" aria-live="polite">
      <Kpi label="Weekly target">{fmtT(target)} t</Kpi>
      <Kpi label={`Week ${focus.week} expected`}>{fmtT(focus.expected_kg)} t</Kpi>
      {gap ? <Kpi label={`Week ${gap.week} gap`} cls="amber">{fmtT(gap.gap_kg)} t short</Kpi> : <Kpi label="Gap" cls="mint">None</Kpi>}
      <Kpi label="Calls" extra={calls.length ? <div className="bar"><i style={{ width: `${(done / calls.length) * 100}%` }} /></div> : null}>
        {calls.length ? <span>{done} <small>of {calls.length} done</small></span> : "None yet"}
      </Kpi>
    </div>
  );
}
