import { useEffect, useState } from "react";
import { toast } from "sonner";
import { campaignsOf, CROPS, useCrop, useMembership } from "../campaigns.jsx";
import FarmerForm from "../components/setup/FarmerForm.jsx";
import FarmerList from "../components/setup/FarmerList.jsx";
import FarmerSheet from "../components/setup/FarmerSheet.jsx";
import { api, apiUrl, cachedGet, can, fmtKg, maskPhone, peekGet } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { useAct } from "../toast.jsx";
import { ActButton, Dialog, DialogClose, needs } from "../ui.jsx";

const SAMPLE_CSV = "name,phone,crop,language,village,usual_kg_week,can_pull_forward\nPak Contoh,+62 812 0000 5001,palm,Bahasa Indonesia,Sungai Lala,1500,yes";

// The farmer database: every farmer of the mill, whatever their crop or campaign. Each campaign shows only
// its own farmers; here they are moved between campaigns (the Campaign column) or kept in none.
export default function Farmers() {
  const { state } = useLive();
  const act = useAct();
  const { ofFarmer } = useMembership(state);
  const camps = campaignsOf(state);
  const [crop, setCrop] = useState("");
  const [camp, setCamp] = useState(""); // "" all, "none" in no campaign, or a campaign id
  const [kind, setKind] = useState("farmers"); // farmers or suppliers
  const [farmerForm, setFarmerForm] = useState(null);
  const [openFarmer, setOpenFarmer] = useState(null);
  const [upload, setUpload] = useState(false);
  const [csv, setCsv] = useState(SAMPLE_CSV);
  const [uploadTo, setUploadTo] = useState("");

  const all = state?.farmers || [];
  const list = all.filter((f) => (kind === "suppliers" ? f.type === "supplier" : f.type !== "supplier"))
    .filter((f) => !crop || f.crop === crop)
    .filter((f) => !camp || (camp === "none" ? !ofFarmer(f) : ofFarmer(f) === camp))
    .sort((a, b) => a.name.localeCompare(b.name));
  const none = all.filter((f) => f.type !== "supplier" && !ofFarmer(f)).length;

  const doUpload = () => act(async () => {
    const r = await api("/api/farmers/upload", { body: { csv, campaign_id: uploadTo } });
    setUpload(false);
    return r;
  }, (r) => {
    if (r.skipped?.length) {
      toast.warning(`${r.skipped.length} line${r.skipped.length > 1 ? "s" : ""} skipped`, {
        description: <ul className="skipped">{r.skipped.slice(0, 8).map((x) => <li key={x}>{x}</li>)}</ul>, duration: Infinity, closeButton: true });
    }
    return `${r.added} farmers saved.`;
  });

  const head = (
    <div className="page-head">
      <div>
        <h1>Farmer database</h1>
        <p>Every farmer the mill works with. A campaign calls only the farmers in it; {none ? `${none} farmers are in no campaign right now.` : "every farmer is in a campaign."}</p>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn" type="button" onClick={() => setUpload(true)} {...needs("farmers.manage")}>Upload CSV</button>
        <button className="btn solid" type="button" onClick={() => setFarmerForm({ crop: crop || "palm", campaign_id: camp && camp !== "none" ? camp : "" })} {...needs("farmers.manage")}>Add farmer</button>
      </div>
    </div>
  );

  const filters = (
    <>
      <select className="filter-select" aria-label="Show farmers or suppliers" value={kind} onChange={(e) => setKind(e.target.value)}>
        <option value="farmers">Farmers</option><option value="suppliers">Suppliers</option>
      </select>
      <select className="filter-select" aria-label="Filter by crop" value={crop} onChange={(e) => { setCrop(e.target.value); setCamp(""); }}>
        <option value="">All crops</option>
        {CROPS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
      </select>
      <select className="filter-select" aria-label="Filter by campaign" value={camp} onChange={(e) => setCamp(e.target.value)}>
        <option value="">All campaigns</option>
        <option value="none">In no campaign</option>
        {camps.filter((c) => !crop || c.crop === crop).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
      </select>
    </>
  );

  return (
    <Shell title="Farmers" head={head}>
      {state && <Traceability />}
      {state && <FarmerList farmers={list} onEdit={setFarmerForm} onOpen={setOpenFarmer} showCampaign title={kind === "suppliers" ? "Suppliers" : "All farmers"} filters={filters}
        empty={all.length ? "No farmer matches these filters." : "No farmers yet. Add one, or upload a CSV."} />}
      <FarmerSheet farmer={openFarmer} state={state} onClose={() => setOpenFarmer(null)} />
      <FarmerForm farmer={farmerForm} onClose={() => setFarmerForm(null)} />
      <Dialog open={upload} onClose={() => setUpload(false)} title="Upload farmers">
        <p className="muted" style={{ margin: "8px 0" }}>
          One farmer per line. Required: name, phone, crop (palm, rubber or coffee), language. Optional: village, usual_kg_week, can_pull_forward (yes or no).
          A phone already in the database updates that farmer. <a href="/farmers-template.csv" download>Download the template</a>.
        </p>
        <label className="field" style={{ marginBottom: 8 }}>Put them in
          <select value={uploadTo} onChange={(e) => setUploadTo(e.target.value)}>
            <option value="">No campaign (the database only)</option>
            {camps.map((c) => <option key={c.id} value={c.id}>{c.label} (only its crop's rows)</option>)}
          </select>
        </label>
        <input type="file" accept=".csv,text/csv" aria-label="CSV file" style={{ marginBottom: 8 }}
          onChange={async (e) => { const f = e.target.files[0]; if (f) setCsv(await f.text()); }} />
        <textarea aria-label="CSV text" value={csv} onChange={(e) => setCsv(e.target.value)} />
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <ActButton className="btn solid" busy="Uploading…" run={doUpload}>Upload</ActButton>
          <DialogClose>Cancel</DialogClose>
        </div>
      </Dialog>
    </Shell>
  );
}


// Where the fruit comes from: how many of the campaign's farmers have a mapped plot and a certification, who
// delivers more than their plot can grow, and the traceability file for buyers (EUDR, RSPO, ISPO).
function Traceability() {
  const { state } = useLive();
  const { cid, campaign } = useCrop();
  const url = `/api/traceability?campaign=${encodeURIComponent(cid)}`;
  const [got, setT] = useState(() => peekGet(url) || null);
  const t = got || peekGet(url);
  const key = JSON.stringify(state.farmers.map((f) => [f.id, f.plot_lat, f.plot_ha, f.certification, f.campaign_id]));
  useEffect(() => {
    let live = true;
    cachedGet(url).then((r) => { if (live) setT(r); }).catch(() => {});
    return () => { live = false; };
  }, [url, key]);
  if (!t) return <section className="card trace-card trace-wait" aria-hidden="true" />;  // holds the space until it loads
  const pct = (n) => (t.farmers ? Math.round((n / t.farmers) * 100) : 0);
  return (
    <section className="card trace-card" aria-labelledby="trace-title">
      <div className="card-head">
        <h2 id="trace-title">Traceability · {campaign.label}</h2>
        <a className="btn sm" href={apiUrl(`/api/traceability.csv?campaign=${encodeURIComponent(cid)}`)} download="traceability.csv">Traceability CSV</a>
      </div>
      <dl className="trace-rows">
        <div><dt>Plot on the map</dt><dd><span className="meter" aria-hidden="true"><i style={{ width: `${pct(t.mapped)}%` }} /></span><b className="num">{t.mapped}</b> of {t.farmers} farmers</dd></div>
        <div><dt>Certified (ISPO or RSPO)</dt><dd><span className="meter" aria-hidden="true"><i style={{ width: `${pct(t.certified)}%` }} /></span><b className="num">{t.certified}</b> of {t.farmers} farmers</dd></div>
      </dl>
      {t.over_plot_yield.length > 0 ? (
        <div className="trace-flag" role="note">
          <b>{t.over_plot_yield.length === 1 ? "One farmer delivers" : `${t.over_plot_yield.length} farmers deliver`} more than their plot can grow.</b>
          <ul>
            {t.over_plot_yield.slice(0, 5).map((x) => (
              <li key={x.farmer_id}>{x.name}: {fmtKg(x.delivered_kg_year)} kg in a year from a plot that grows about {fmtKg(x.max_kg_year)} kg. Check where the fruit comes from.</li>
            ))}
          </ul>
        </div>
      ) : <p className="small muted" style={{ margin: 0 }}>No farmer delivers more than their plot can grow.</p>}
      <p className="small muted" style={{ margin: 0 }}>Each delivery in the CSV carries the farmer's plot location, area and certification. Add a plot on the farmer's Edit form.</p>
    </section>
  );
}
