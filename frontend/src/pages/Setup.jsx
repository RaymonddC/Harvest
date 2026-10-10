import { useState } from "react";
import FarmerForm from "../components/setup/FarmerForm.jsx";
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
  const [farmerForm, setFarmerForm] = useState(null); // {} to add, a farmer to edit, null when closed
  const farmers = state ? state.farmers.filter((f) => f.type !== "supplier")
    .sort((a, b) => Number(!!b.to_call) - Number(!!a.to_call) || a.id.localeCompare(b.id)) : [];
  const toCall = state ? state.farmers.filter((f) => f.to_call).length : 0;
  const l = state ? state.limits[0] : null;

  const head = (
    <div className="page-head">
      <div>
        <h1>Set up this week's calls</h1>
        <p>Three quick steps. Once the price range is set, one click calls every farmer.</p>
      </div>
    </div>
  );

  return (
    <Shell title="Setup" head={head}>
      {/* "linked": on a wide screen a line joins each step to the next, green once the step is done. */}
      <div className="steps linked">
        <FarmersStep farmers={farmers} toCall={toCall} onAdd={() => setFarmerForm({})} />
        <PriceRange l={l} />
        {state ? <StartCalling state={state} toCall={toCall} /> : <section className="card dark"><div className="stats" id="campaign-lines" /></section>}
      </div>
      {state && <FarmerList farmers={farmers} onEdit={setFarmerForm} />}
      <FarmerForm farmer={farmerForm} onClose={() => setFarmerForm(null)} />
      <p className="small muted">All data is synthetic. <button className="btn sm" type="button" style={{ marginLeft: 8 }} onClick={() => act(() => api("/api/demo/reset"), "Demo data reset.")}>Reset demo data</button></p>
    </Shell>
  );
}
