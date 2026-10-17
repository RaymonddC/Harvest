import { api, can, fmtT } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton } from "../../ui.jsx";

// A second opinion on the coming weeks: BigQuery ML (ARIMA_PLUS) trained on the weighbridge's daily net deliveries,
// next to what the farmers said on the calls. Written by the hourly BigQuery job (backend bq_export.py).
export default function MlForecast({ state, crop, rows }) {
  const act = useAct();
  const days = (state.ml_forecast || []).filter((d) => d.crop === crop);
  const on = !!state.settings?.bigquery;
  if (!on && !days.length) return null;
  const weeks = rows.filter((r) => !r.before_start).slice(0, 4).map((r) => {
    const start = r.week_start;
    const end = new Date(new Date(`${start}T00:00:00`).getTime() + 6 * 864e5).toISOString().slice(0, 10);
    const inWeek = days.filter((d) => d.day >= start && d.day <= end);
    const kg = inWeek.reduce((n, d) => n + d.kg, 0);
    return { label: r.label, said: r.expected_kg, ml: inWeek.length ? kg : null, low: inWeek.reduce((n, d) => n + d.low, 0), high: inWeek.reduce((n, d) => n + d.high, 0) };
  });
  const made = days[0]?.made_at;
  return (
    <section className="card ml-card" aria-labelledby="ml-title">
      <div className="card-head"><h2 id="ml-title">What the history says</h2></div>
      {days.length ? (
        <>
          <p className="small muted" style={{ margin: 0 }}>BigQuery ML forecast from the weighbridge's past deliveries, next to what farmers told the agent.</p>
          <table className="ml-table">
            <thead><tr><th>Week</th><th className="r">Farmers said</th><th className="r">History says</th></tr></thead>
            <tbody>
              {weeks.map((w) => (
                <tr key={w.label}>
                  <td>{w.label}</td>
                  <td className="r num">{fmtT(w.said)} t</td>
                  <td className="r num" title={w.ml != null ? `Likely range ${fmtT(w.low)} to ${fmtT(w.high)} t` : undefined}>{w.ml != null ? `${fmtT(w.ml)} t` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted" style={{ margin: 0 }}>Trained {made ? new Date(made).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}. A big difference means the answers or the history need a second look.</p>
        </>
      ) : <p className="small muted" style={{ margin: 0 }}>The first BigQuery run has not finished yet. It runs every hour.</p>}
      {on && can("campaign.run") && (
        <ActButton className="btn sm" busy="Sending to BigQuery…" run={() => act(() => api("/api/bigquery/export", { body: {} }),
          (r) => `Sent to BigQuery${r.ml_forecast?.days ? `; forecast for ${r.ml_forecast.days} days` : ""}.`)}>Refresh from BigQuery</ActButton>
      )}
    </section>
  );
}
