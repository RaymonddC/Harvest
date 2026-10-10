import { useState } from "react";
import FarmerList from "../components/setup/FarmerList.jsx";
import FarmersStep from "../components/setup/FarmersStep.jsx";
import PriceRange from "../components/setup/PriceRange.jsx";
import StartCalling from "../components/setup/StartCalling.jsx";
import { api } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { useAct } from "../toast.jsx";

export default function Setup() {
  const { state } = useLive();
  const act = useAct();
  const [unsaved, setUnsaved] = useState(false);
  const farmers = state ? state.farmers.filter((f) => f.type !== "supplier")
    .sort((a, b) => Number(!!b.to_call) - Number(!!a.to_call) || a.id.localeCompare(b.id)) : [];
  const toCall = state ? state.farmers.filter((f) => f.to_call).length : 0;
  const l = state ? state.limits[0] : null;
  const running = state && (state.campaigns.find((x) => x.id === "current") || {}).status === "running";
  const priced = !!l && !unsaved;

  const head = (
    <div className="page-head">
      <div>
        <h1>Set up this week's calls</h1>
        <p>Three quick steps. Once the price range is set, one click calls every farmer.</p>
      </div>
      <div className="chips" aria-label="Setup progress">
        {state && <>
          <span className={`pill lg ${farmers.length ? "mint" : ""}`}>{farmers.length ? "1 Farmers ✓" : "1 Farmers"}</span>
          <span className={`pill lg ${priced ? "mint" : ""}`}>{priced ? "2 Price range ✓" : "2 Price range"}</span>
          <span className="pill lg now">{running ? "3 Calling" : "3 Start calling"}</span>
        </>}
      </div>
    </div>
  );

  return (
    <Shell title="Setup" head={head}>
      <div className="steps">
        <FarmersStep farmers={farmers} toCall={toCall} />
        <PriceRange l={l} onDirty={setUnsaved} />
        {state ? <StartCalling state={state} toCall={toCall} /> : <section className="card dark"><div className="stats" id="campaign-lines" /></section>}
      </div>
      {state && <FarmerList farmers={farmers} />}
      <p className="small muted">All data is synthetic. <button className="btn sm" type="button" style={{ marginLeft: 8 }} onClick={() => act(() => api("/api/demo/reset"), "Demo data reset.")}>Reset demo data</button></p>
    </Shell>
  );
}
