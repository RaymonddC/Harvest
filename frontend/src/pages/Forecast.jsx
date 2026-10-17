import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import CallRecap from "../components/forecast/CallRecap.jsx";
import { CallLog, Calls } from "../components/forecast/Calls.jsx";
import Chart from "../components/forecast/Chart.jsx";
import { FillList, Hero } from "../components/forecast/GapCard.jsx";
import GapNote from "../components/forecast/GapNote.jsx";
import Kpis from "../components/forecast/Kpis.jsx";
import SupplyChart from "../components/forecast/SupplyChart.jsx";
import SurplusCard from "../components/forecast/SurplusCard.jsx";
import TargetBreakdown from "../components/forecast/TargetBreakdown.jsx";
import TrackRecord from "../components/forecast/TrackRecord.jsx";
import { unknownSupply } from "../components/setup/NeedPanel.jsx";
import { apiUrl, fmtT } from "../lib.js";
import { campaignFor, forCrop, inCampaign, useCrop } from "../campaigns.jsx";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { SegToggle } from "../ui.jsx";

const PERIODS = [["day", "Day"], ["week", "Week"], ["month", "Month"], ["year", "Year"]];
const PERIOD_KEY = "harvestPeriod";

export default function Forecast() {
  const [period, setPeriodState] = useState(() => { try { return localStorage.getItem(PERIOD_KEY) || "week"; } catch { return "week"; } });
  const setPeriod = (p) => { setPeriodState(p); try { localStorage.setItem(PERIOD_KEY, p); } catch { /* storage blocked */ } };
  const { state } = useLive();
  const [shown, setShown] = useState(null); // call in the detail dialog
  const [logOpen, setLogOpen] = useState(false);
  const { cid, crop, campaign: picked } = useCrop();
  const rows = state ? inCampaign(state, state.forecast, cid).sort((a, b) => a.week - b.week) : []; // the picked campaign's weeks
  const gap = rows.find((r) => r.is_gap);
  // Everything below shows the picked campaign only: its farmers, their calls and offers; the crop's rival quotes.
  const view = state ? { ...state, farmers: inCampaign(state, state.farmers, cid), offers: inCampaign(state, state.offers, cid),
    rival_quotes: forCrop(state.rival_quotes, crop), calls: inCampaign(state, state.calls, cid) } : null;
  const campaign = state ? campaignFor(state, cid) : {};
  const running = campaign.status === "running";
  const campaignCalls = view ? view.calls.filter((c) => c.kind !== "confirm" && (c.attempt || 1) === 1) : [];
  const target = rows.length ? rows[0].target_kg : 0;

  const head = (
    <div className="page-head">
      <div>
        <h1>Live supply forecast</h1>
        <p>Expected supply for {picked.label || "this campaign"} per week against its target, updated as each call is saved.</p>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        <span className={`pill lg dot ${running ? "mint running" : ""}`}>{running ? (campaign.kind === "gap_fill" ? "Gap-fill calls running" : "Campaign running") : "No campaign running"}</span>
        <a className="btn" href={apiUrl(`/api/forecast.csv?campaign=${encodeURIComponent(cid)}`)} download="forecast.csv">Export CSV</a>
      </div>
    </div>
  );

  return (
    <Shell title="Live forecast" head={head}>
      {/* The page's one message first: the gap and how to fill it, or that every week is fine.
          initial={false}: no fade when the page opens, only when the gap opens or closes. */}
      <AnimatePresence mode="wait" initial={false}>
        {state && rows.length > 0 && (
          <motion.div key={gap ? "gap" : "ok"} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.25, ease: "easeOut" }}>
            <Hero gap={gap} rows={rows} state={view} />
          </motion.div>
        )}
      </AnimatePresence>
      <Kpis rows={rows} calls={campaignCalls} toCall={state ? unknownSupply(state, cid).toCall.length : 0} />
      {state && rows.length > 0 && (
        <section className="card" aria-labelledby="stand-title">
          <div className="card-head"><h2 id="stand-title">Where each week's target stands</h2></div>
          <TargetBreakdown rows={rows} unknownKg={unknownSupply(state, cid).usualKg} />
        </section>
      )}
      <div className="cols">
        <div className="col-main">
          <section className="card" aria-labelledby="chart-title">
            <div className="card-head">
              <h2 id="chart-title">Expected supply vs target, tonnes per {period}</h2>
              <SegToggle label="Show by" options={PERIODS} value={period} onChange={setPeriod} />
            </div>
            {period !== "week" ? (state && <SupplyChart cid={cid} period={period} refreshKey={JSON.stringify(rows.map((r) => r.expected_kg))} />) : <>
            <div className="card-head" style={{ marginTop: -6 }}>
              <div className="legend" aria-hidden="true">
                <span><i className="l-leaf" />Firm</span>
                <span><i className="l-unsure" />Unsure, counted half</span>
                <span><i className="l-projected" />Later rounds (projected)</span>
                <span><i className="l-approved" />Approved deals</span>
                <span><i className="l-amber" />Gap week</span>
                <span><i className="l-pend" />Pending approval</span>
                {rows[0]?.capacity_kg ? <span><i className="l-cap" />Mill capacity</span> : null}
                <span><i className="l-target" /><span>{target ? `Target ${fmtT(target)} t` : "Target"}</span></span>
              </div>
            </div>
            <div id="chart-area">
              {rows.length > 0 ? <Chart rows={rows} />
                : state ? <div className="empty"><p>No forecast yet. Start a call campaign to collect harvest answers.</p><Link className="btn" to="/setup">Go to setup</Link></div> : null}
            </div>
            <GapNote gap={gap} />
            </>}
            <p className="small muted">Unsure answers count for half; later harvest rounds are projected from how often each farmer harvests. Deliveries are net, after grading. All data is synthetic.</p>
          </section>
          {state && <TrackRecord cid={cid} rows={rows} refreshKey={JSON.stringify(rows.map((r) => r.expected_kg))} />}
        </div>
        <div className="col-side">
          {state && gap && <FillList gap={gap} state={view} />}
          {state && rows.find((r) => r.is_surplus) && <SurplusCard row={rows.find((r) => r.is_surplus)} cid={cid} />}
          <section className="card" aria-labelledby="calls-title">
            <div className="card-head">
              <h2 id="calls-title">Calls</h2>
              <Link to="/calls">Open the calls</Link>
            </div>
            {state ? <Calls calls={view.calls} onShow={setShown} /> : <div className="rows" id="calls" />}
            <button className="btn" onClick={() => setLogOpen(true)}>Call log</button>
          </section>
        </div>
      </div>
      <CallRecap call={shown} onClose={() => setShown(null)} />
      <CallLog open={logOpen} calls={view ? view.calls : []} onClose={() => setLogOpen(false)} onShow={setShown} />
    </Shell>
  );
}
