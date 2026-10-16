import { useState } from "react";
import { Link } from "react-router-dom";
import { campaignFor, cropName, inCampaign, useCrop } from "../campaigns.jsx";
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
import { ActButton, Icon } from "../ui.jsx";

// One campaign: pick or edit it, then its three steps (its farmers, the crop's price range, start calling).
export default function Setup() {
  const { state } = useLive();
  const act = useAct();
  const [farmerForm, setFarmerForm] = useState(null); // {} to add, a farmer to edit, null when closed
  const [openFarmer, setOpenFarmer] = useState(null); // the farmer whose page is open
  const { cid, crop } = useCrop();
  const campaign = state ? campaignFor(state, cid) : {};
  const farmers = state ? inCampaign(state, state.farmers, cid).filter((f) => f.type !== "supplier")
    .sort((a, b) => Number(!!b.to_call) - Number(!!a.to_call) || a.id.localeCompare(b.id)) : [];
  const toCall = farmers.filter((f) => f.to_call).length;
  const l = state ? state.limits.find((x) => (x.crop || x.id) === crop) || null : null; // none yet for a new crop: the form starts blank
  const persona = campaign.persona || {};

  const head = (
    <div className="page-head">
      <div>
        <h1>Campaigns</h1>
        <p>Pick a campaign, then three quick steps for it. Once the price range is set, one click calls its farmers.</p>
      </div>
    </div>
  );

  return (
    <Shell title="Campaign" head={head}>
      {state && <Campaigns state={state} />}
      {/* "linked": on a wide screen a line joins each step to the next, green once the step is done. */}
      <div className="steps linked">
        <FarmersStep farmers={farmers} toCall={toCall} cid={cid} crop={crop} onAdd={() => setFarmerForm({ crop, campaign_id: cid })} />
        <PriceRange key={crop} l={l} crop={crop} />
        {state ? <StartCalling state={state} toCall={toCall} /> : <section className="card dark"><div className="stats" id="campaign-lines" /></section>}
      </div>
      {state && campaign.id && (
        <section className="card agent-link" aria-label="The agent">
          <span className="agent-link-icon"><Icon name="agent" size={20} /></span>
          <div>
            <b>{persona.name || "The agent"}</b>
            <span className="sub">{persona.preset || persona.style ? `${persona.style || persona.preset} · ` : ""}{(campaign.questions || []).length} extra question{(campaign.questions || []).length === 1 ? "" : "s"} on harvest calls</span>
          </div>
          <Link className="btn" to="/agent">Set up the agent</Link>
        </section>
      )}
      {state && (
        <FarmerList farmers={farmers} onEdit={setFarmerForm} onOpen={setOpenFarmer} cid={cid}
          title={`Farmers in ${campaign.label || cropName(crop)}`}
          empty={<>No farmers in this campaign yet. Use <b>Add from database</b> above, or the <Link to="/farmers">Farmers</Link> page.</>} />
      )}
      <FarmerSheet farmer={openFarmer} state={state} onClose={() => setOpenFarmer(null)} />
      <FarmerForm farmer={farmerForm} onClose={() => setFarmerForm(null)} />
      <p className="small muted">All data is synthetic. <ActButton need="demo.reset" className="btn sm" busy="Resetting…" style={{ marginLeft: 8 }} run={() => act(() => api("/api/demo/reset"), "Demo data reset.")}>Reset demo data</ActButton></p>
    </Shell>
  );
}
