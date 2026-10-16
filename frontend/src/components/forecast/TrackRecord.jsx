import { useEffect, useState } from "react";
import { api, can } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton } from "../../ui.jsx";

const t = (kg) => `${(kg / 1000).toFixed(1)} t`;
const pct = (x) => `${Math.round(x * 100)}%`;
const day = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
const SAMPLE = "phone,date,kg\n+62 810 0000 1000,2026-10-14,1450";

// Closing the loop: what farmers promised against what the weighbridge recorded, how many keep their word,
// and the supply to expect given their record (next to what they said). Deliveries come in as a CSV here,
// or one at a time on a farmer's page.
export default function TrackRecord({ cid, rows, refreshKey }) {
  const act = useAct();
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false);
  const [csv, setCsv] = useState(SAMPLE);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    api(`/api/track-record?campaign=${encodeURIComponent(cid)}`, { method: "GET" }).then((d) => { if (live) setData(d); }).catch(() => {});
    return () => { live = false; };
  }, [cid, refreshKey, tick]);

  const upload = async () => {
    const r = await act(() => api("/api/deliveries/upload", { body: { csv } }),
      (x) => `${x.added} deliveries recorded${x.problems.length ? `; ${x.problems.length} lines skipped (${x.problems[0]})` : ""}.`);
    if (r) { setOpen(false); setTick((n) => n + 1); }
  };
  const readFile = async (e) => { const f = e.target.files?.[0]; if (f) setCsv(await f.text()); };

  if (!data) return null;
  const max = Math.max(1, ...data.weeks.flatMap((w) => [w.promised, w.delivered]));
  const likely = data.likely || {};
  return (
    <section className="card track-card" aria-labelledby="track-title">
      <div className="card-head">
        <h2 id="track-title">Track record</h2>
        <button type="button" className="btn sm" disabled={!can("farmers.manage")} onClick={() => setOpen(!open)}>{open ? "Close" : "Record deliveries"}</button>
      </div>
      {open && (
        <div className="track-upload">
          <p className="small muted">Paste or pick the weighbridge CSV: <b>date</b> and <b>kg</b>, and the farmer by <b>phone</b> (best), <b>farmer_id</b> or exact <b>name</b>. Single deliveries can be added on a farmer's page.</p>
          <input type="file" accept=".csv,text/csv" aria-label="Deliveries CSV file" onChange={readFile} />
          <textarea aria-label="Deliveries CSV" rows={4} value={csv} onChange={(e) => setCsv(e.target.value)} />
          <ActButton className="btn sm leaf" busy="Recording…" run={upload}>Record deliveries</ActButton>
        </div>
      )}
      {data.weeks.length ? (
        <>
          <p className="track-headline">
            {data.accuracy != null && <><b>{pct(data.accuracy)}</b> forecast accuracy over the last {data.weeks.length} weeks with deliveries. </>}
            {data.farmers_rated > 0 && <>{data.reliable} of {data.farmers_rated} farmers with a record deliver at least 90% of what they promise{data.unreliable ? `; ${data.unreliable} deliver less than 70%` : ""}.</>}
          </p>
          <div className="track-bars" role="img" aria-label={data.weeks.map((w) => `week of ${day(w.week_start)}: promised ${t(w.promised)}, delivered ${t(w.delivered)}`).join("; ")}>
            {data.weeks.map((w) => (
              <div key={w.week_start} className="tb">
                <div className="tb-pair">
                  <i className="p" style={{ height: `${(w.promised / max) * 100}%` }} title={`Promised ${t(w.promised)}`} />
                  <i className="d" style={{ height: `${(w.delivered / max) * 100}%` }} title={`Delivered ${t(w.delivered)}`} />
                </div>
                <span>{day(w.week_start)}</span>
                {w.accuracy != null && <small>{pct(w.accuracy)}</small>}
              </div>
            ))}
          </div>
          <div className="legend small"><span><i className="l-promised" />Promised</span><span><i className="l-delivered" />Delivered</span></div>
          {rows.length > 0 && Object.keys(likely).length > 0 && (
            <div className="likely">
              <h3>Likely, given each farmer's record</h3>
              <ul>
                {rows.map((r) => {
                  const l = likely[r.id];
                  if (l == null) return null;
                  const less = r.expected_kg - l;
                  return <li key={r.id}><span>{r.label}</span><b>{t(l)}</b><small className="muted">{less > 50 ? `farmers said ${t(r.expected_kg)}` : "as said"}</small></li>;
                })}
              </ul>
              <p className="small muted">The forecast above shows what farmers said. This scales each farmer's part by the share of promises they delivered (farmers with fewer than 2 recorded weeks count in full).</p>
            </div>
          )}
        </>
      ) : <p className="muted">No deliveries recorded yet. Record the weighbridge deliveries each week to see how accurate the forecast is and which farmers keep their word.</p>}
    </section>
  );
}
