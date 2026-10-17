import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { campaignFor, cropName, inCampaign, useCrop } from "../campaigns.jsx";
import Campaigns from "../components/setup/Campaigns.jsx";
import FarmerForm from "../components/setup/FarmerForm.jsx";
import FarmerSheet from "../components/setup/FarmerSheet.jsx";
import FarmersStep from "../components/setup/FarmersStep.jsx";
import NeedPanel from "../components/setup/NeedPanel.jsx";
import FarmerPipeline from "../components/setup/FarmerPipeline.jsx";
import { toCallOf } from "../crm.js";
import PriceRange from "../components/setup/PriceRange.jsx";
import StartCalling from "../components/setup/StartCalling.jsx";
import { api } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { useAct } from "../toast.jsx";
import { ActButton } from "../ui.jsx";

// One campaign: pick or edit it, then its three steps (its farmers, the crop's price range, start calling).
export default function Setup() {
  const { state } = useLive();
  const act = useAct();
  const [farmerForm, setFarmerForm] = useState(null); // {} to add, a farmer to edit, null when closed
  const [openFarmer, setOpenFarmer] = useState(null); // the farmer whose page is open
  const [chartFilter, setChartFilter] = useState(null); // { ids: Set, label } from a click on the chart above
  const { cid, crop } = useCrop();
  const { hash } = useLocation();
  // Links to /setup#need (the sidebar's To do list) open at the mill's need.
  useEffect(() => { if (hash === "#need" && state) document.getElementById("need")?.scrollIntoView({ block: "start" }); }, [hash, !!state]); // eslint-disable-line react-hooks/exhaustive-deps
  const campaign = state ? campaignFor(state, cid) : {};
  const farmers = state ? inCampaign(state, state.farmers, cid).filter((f) => f.type !== "supplier")
    .sort((a, b) => a.id.localeCompare(b.id)) : [];
  const toCall = state ? toCallOf(state, cid).toCall.length : 0;
  const l = state ? state.limits.find((x) => (x.crop || x.id) === crop) || null : null; // none yet for a new crop: the form starts blank

  const head = (
    <div className="page-head">
      <div>
        <h1>Campaign</h1>
        <p>Who the agent calls, at what price, and when.</p>
      </div>
    </div>
  );

  return (
    <Shell title="Campaign" head={head}>
      {state && <Campaigns state={state} />}
      {state && campaign.id && <NeedPanel state={state} cid={cid} campaign={campaign} onPick={(f) => { setChartFilter(f); setTimeout(() => document.getElementById("farmer-list")?.scrollIntoView({ block: "start", behavior: "smooth" }), 50); }} />}
      {/* "linked": on a wide screen a line joins each step to the next, green once the step is done. */}
      <div className="steps linked">
        <FarmersStep farmers={farmers} toCall={toCall} cid={cid} crop={crop} onAdd={() => setFarmerForm({ crop, campaign_id: cid })} />
        <PriceRange key={crop} l={l} crop={crop} />
        {state ? <StartCalling state={state} toCall={toCall} /> : <section className="card dark"><div className="stats" id="campaign-lines" /></section>}
      </div>
      {state && (
        <FarmerPipeline state={state} cid={cid} onEdit={setFarmerForm} onOpen={setOpenFarmer}
          title={`Farmers in ${campaign.label || cropName(crop)}`} filter={chartFilter} onClearFilter={() => setChartFilter(null)}
          empty={<>No farmers in this campaign yet. Use <b>Add from database</b> above, or the <Link to="/farmers">Farmers</Link> page.</>} />
      )}
      <FarmerSheet farmer={openFarmer} state={state} onClose={() => setOpenFarmer(null)} />
      <FarmerForm farmer={farmerForm} onClose={() => setFarmerForm(null)} />
      <p className="small muted">All data is synthetic. <ActButton need="demo.reset" className="btn sm" busy="Resetting…" style={{ marginLeft: 8 }} run={() => act(() => api("/api/demo/reset"), "Demo data reset.")}>Reset demo data</ActButton></p>
    </Shell>
  );
}
