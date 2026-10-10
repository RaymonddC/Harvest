import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { CallDialog, CallLog, Calls } from "../components/forecast/Calls.jsx";
import Chart from "../components/forecast/Chart.jsx";
import { GapCard, OkCard } from "../components/forecast/GapCard.jsx";
import GapNote from "../components/forecast/GapNote.jsx";
import Kpis from "../components/forecast/Kpis.jsx";
import { apiUrl, cropLabel, fmtT } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";

export default function Forecast() {
  const { state } = useLive();
  const [shown, setShown] = useState(null); // call in the detail dialog
  const [logOpen, setLogOpen] = useState(false);
  const rows = state ? [...state.forecast].sort((a, b) => a.week - b.week) : [];
  const gap = rows.find((r) => r.is_gap);
  const campaign = state ? state.campaigns.find((x) => x.id === "current") || {} : {};
  const running = campaign.status === "running";
  const crop = state && state.limits[0] ? state.limits[0].crop : "palm";
  const campaignCalls = state ? state.calls.filter((c) => c.kind !== "confirm" && (c.attempt || 1) === 1) : [];
  const target = rows.length ? rows[0].target_kg : 0;

  const head = (
    <div className="page-head">
      <div>
        <h1>Live supply forecast</h1>
        <p>Expected {cropLabel(crop)} per week against the mill's target, updated as each call is saved.</p>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        <span className={`pill lg dot ${running ? "mint running" : ""}`}>{running ? (campaign.kind === "gap_fill" ? "Gap-fill calls running" : "Campaign running") : "No campaign running"}</span>
        <a className="btn" href={apiUrl("/api/forecast.csv")} download="forecast.csv">Export CSV</a>
      </div>
    </div>
  );

  return (
    <Shell title="Live forecast" head={head}>
      <Kpis rows={rows} calls={campaignCalls} toCall={state ? state.farmers.filter((f) => f.to_call).length : 0} />
      <div className="cols">
        <div className="col-main">
          <section className="card" aria-labelledby="chart-title">
            <div className="card-head">
              <h2 id="chart-title">Expected supply vs target, tonnes per week</h2>
              <div className="legend" aria-hidden="true">
                <span><i className="l-leaf" />On track</span>
                <span><i className="l-amber" />Gap</span>
                <span><i className="l-pend" />Pending approval</span>
                <span><i className="l-target" /><span>{target ? `Target ${fmtT(target)} t` : "Target"}</span></span>
              </div>
            </div>
            <div id="chart-area">
              {rows.length > 0 ? <Chart rows={rows} />
                : state ? <div className="empty"><p>No forecast yet. Start a call campaign to collect harvest answers.</p><Link className="btn" to="/setup">Go to setup</Link></div> : null}
            </div>
            <GapNote gap={gap} />
            <p className="small muted">Unsure answers count for half. All data is synthetic.</p>
          </section>
        </div>
        <div className="col-side">
          {/* initial={false}: no fade when the page opens, only when the gap opens or closes. */}
          <AnimatePresence mode="wait" initial={false}>
            {state && rows.length > 0 && (
              <motion.div key={gap ? "gap" : "ok"} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.25, ease: "easeOut" }}>
                {gap ? <GapCard gap={gap} state={state} /> : <OkCard state={state} />}
              </motion.div>
            )}
          </AnimatePresence>
          <section className="card" aria-labelledby="calls-title">
            <div className="card-head">
              <h2 id="calls-title">Live calls</h2>
              <a href="/call.html" target="_blank" rel="noopener">Open call client</a>
            </div>
            {state ? <Calls calls={state.calls} onShow={setShown} /> : <div className="rows" id="calls" />}
            <button className="btn" onClick={() => setLogOpen(true)}>Call log</button>
          </section>
        </div>
      </div>
      <CallDialog call={shown} onClose={() => setShown(null)} />
      <CallLog open={logOpen} calls={state ? state.calls : []} onClose={() => setLogOpen(false)} onShow={setShown} />
    </Shell>
  );
}
