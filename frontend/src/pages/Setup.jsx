import { useState } from "react";
import { cropName, forCrop, useCrop } from "../campaigns.jsx";
import AgentCard from "../components/setup/AgentCard.jsx";
import Campaigns from "../components/setup/Campaigns.jsx";
import FarmerForm from "../components/setup/FarmerForm.jsx";
import FarmerList from "../components/setup/FarmerList.jsx";
import FarmerSheet from "../components/setup/FarmerSheet.jsx";
import FarmersStep from "../components/setup/FarmersStep.jsx";
import PriceRange from "../components/setup/PriceRange.jsx";
import StartCalling from "../components/setup/StartCalling.jsx";
import { api } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { useAct } from "../toast.jsx";
import { ActButton } from "../ui.jsx";

export default function Setup() {
  const { state } = useLive();
  const act = useAct();
  const [farmerForm, setFarmerForm] = useState(null); // {} to add, a farmer to edit, null when closed
  const [openFarmer, setOpenFarmer] = useState(null); // the farmer whose page is open
  const { crop } = useCrop();
  // Everything below is for the picked crop's campaign.
  const farmers = state ? forCrop(state.farmers, crop).filter((f) => f.type !== "supplier")
    .sort((a, b) => Number(!!b.to_call) - Number(!!a.to_call) || a.id.localeCompare(b.id)) : [];
  const toCall = state ? forCrop(state.farmers, crop).filter((f) => f.to_call).length : 0;
  const l = state ? state.limits.find((x) => (x.crop || x.id) === crop) || null : null; // none yet for a new crop: the form starts blank

  const head = (
    <div className="page-head">
      <div>
        <h1>Set up this week's calls</h1>
        <p>Pick a campaign, then three quick steps for it. Once the price range is set, one click calls every {cropName(crop)} farmer.</p>
      </div>
    </div>
  );

  return (
    <Shell title="Setup" head={head}>
      {state && <Campaigns state={state} />}
      {/* "linked": on a wide screen a line joins each step to the next, green once the step is done. */}
      <div className="steps linked">
        <FarmersStep farmers={farmers} toCall={toCall} onAdd={() => setFarmerForm({})} />
        <PriceRange key={crop} l={l} crop={crop} />
        {state ? <StartCalling state={state} toCall={toCall} /> : <section className="card dark"><div className="stats" id="campaign-lines" /></section>}
      </div>
      {state && <AgentCard key={crop} state={state} crop={crop} />}
      {state && <FarmerList farmers={farmers} onEdit={setFarmerForm} onOpen={setOpenFarmer} />}
      <FarmerSheet farmer={openFarmer} state={state} onClose={() => setOpenFarmer(null)} />
      <FarmerForm farmer={farmerForm} onClose={() => setFarmerForm(null)} />
      <p className="small muted">All data is synthetic. <ActButton need="demo.reset" className="btn sm" busy="Resetting…" style={{ marginLeft: 8 }} run={() => act(() => api("/api/demo/reset"), "Demo data reset.")}>Reset demo data</ActButton></p>
    </Shell>
  );
}
