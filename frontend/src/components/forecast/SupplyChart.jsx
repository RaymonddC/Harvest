import { useEffect, useState } from "react";
import { api, fmtT } from "../../lib.js";

// Supply by day, month or year (the week view is the main chart): expected supply ahead, net deliveries behind,
// the target and the mill's capacity for each bar. From GET /api/supply. Arrows move the window.
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };

function windowFor(period, shift) {
  const now = new Date();
  if (period === "day") {
    const start = addDays(now, -7 + shift * 28);
    return [start, addDays(start, 34)];
  }
  if (period === "month") {
    const start = new Date(now.getFullYear(), now.getMonth() - 5 + shift * 6, 1);
    return [start, new Date(start.getFullYear(), start.getMonth() + 9, 0)];
  }
  const y = now.getFullYear() - 1 + shift * 3;
  return [new Date(y, 0, 1), new Date(y + 2, 11, 31)];
}

export default function SupplyChart({ cid, period, refreshKey }) {
  const [shift, setShift] = useState(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { setShift(0); }, [period]);
  useEffect(() => {
    let live = true;
    const [a, b] = windowFor(period, shift);
    api(`/api/supply?period=${period}&start=${iso(a)}&end=${iso(b)}&campaign=${encodeURIComponent(cid)}`, { method: "GET" })
      .then((r) => { if (live) { setData(r); setError(""); } })
      .catch((e) => { if (live) setError(e.message || "Could not load the supply."); });
    return () => { live = false; };
  }, [cid, period, shift, refreshKey]);

  if (error) return <p className="banner error" role="alert">{error}</p>;
  if (!data) return <div className="supply-chart loading" />;
  const rows = data.rows;
  const max = Math.max(1, ...rows.flatMap((r) => [r.expected_kg, r.delivered_kg, r.target_kg, r.capacity_kg || 0])) * 1.1;
  const h = (kg) => `${(kg / max) * 100}%`;
  const over = rows.filter((r) => r.is_surplus && !r.past).length;
  const short = rows.filter((r) => r.is_gap).length;
  const word = { day: "days", month: "months", year: "years" }[period];
  return (
    <div className="supply">
      <div className="supply-bar">
        <button type="button" className="btn sm" aria-label="Earlier" onClick={() => setShift(shift - 1)}>‹</button>
        <span className="small"><b>{rows[0]?.label}</b> to <b>{rows[rows.length - 1]?.label}</b></span>
        <button type="button" className="btn sm" aria-label="Later" onClick={() => setShift(shift + 1)}>›</button>
        {shift !== 0 && <button type="button" className="btn sm ghost" onClick={() => setShift(0)}>Now</button>}
        <span className="small muted" style={{ marginLeft: "auto" }}>
          {data.daily_capacity_kg ? `Mill capacity ${fmtT(data.daily_capacity_kg)} t a day, ${data.working_days} days a week` : "Set the mill's capacity on the campaign to see days over capacity"}
          {short ? `, ${short} ${word} short` : ""}{over ? `, ${over} ${word} over capacity` : ""}
        </span>
      </div>
      <div className={`supply-chart p-${period}`} role="img"
        aria-label={rows.map((r) => `${r.label}: ${r.past ? `delivered ${fmtT(r.delivered_kg)}` : `expected ${fmtT(r.expected_kg)}`} t`).join("; ")}>
        {rows.map((r) => (
          <div key={r.start} className={`sb ${r.past ? "past" : ""} ${r.is_gap ? "gap" : ""} ${r.is_surplus && !r.past ? "over" : ""} ${r.beyond && !r.delivered_kg ? "beyond" : ""}`}
            title={`${r.label}\nExpected ${fmtT(r.expected_kg)} t\nDelivered (net) ${fmtT(r.delivered_kg)} t\nTarget ${fmtT(r.target_kg)} t${r.capacity_kg != null ? `\nCapacity ${fmtT(r.capacity_kg)} t` : ""}${period === "day" && r.trucks ? `\n${r.trucks} truck loads` : ""}`}>
            <div className="sb-plot">
              {r.capacity_kg ? <i className="sb-cap" style={{ bottom: h(r.capacity_kg) }} /> : null}
              {r.target_kg ? <i className="sb-target" style={{ bottom: h(r.target_kg) }} /> : null}
              {r.beyond && !r.delivered_kg && <span className="sb-beyond">not planned yet</span>}
              <i className="sb-exp" style={{ height: h(r.expected_kg) }} />
              {r.delivered_kg > 0 && <i className="sb-del" style={{ height: h(r.delivered_kg) }} />}
            </div>
            <span className="sb-label">{period === "day" ? new Date(`${r.start}T00:00:00`).getDate() : r.label.replace(/ \d{4}$/, period === "month" ? "" : "$&")}</span>
            {period === "day" && <small className="sb-trucks">{r.trucks || ""}</small>}
          </div>
        ))}
      </div>
      <div className="legend small" aria-hidden="true">
        <span><i className="l-leaf" />Expected</span>
        <span><i className="l-arrived" />Delivered (net, after grading)</span>
        <span><i className="l-target" />Target</span>
        <span><i className="l-cap" />Mill capacity</span>
        <span><i className="l-amber" />Short</span>
        <span><i className="l-over" />Over capacity</span>
        {period === "day" && <span>Number under each day: truck loads of {fmtT(data.truck_kg)} t</span>}
      </div>
    </div>
  );
}
