import { useState } from "react";
import { toast } from "sonner";
import { campaignsOf, CROPS, useMembership } from "../campaigns.jsx";
import FarmerForm from "../components/setup/FarmerForm.jsx";
import FarmerList from "../components/setup/FarmerList.jsx";
import FarmerSheet from "../components/setup/FarmerSheet.jsx";
import { api, can, maskPhone } from "../lib.js";
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
  const [allowOpen, setAllowOpen] = useState(false);

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
        {state?.settings?.phone_calls && <button className="btn" type="button" onClick={() => setAllowOpen(true)}>Phone allowlist</button>}
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
      {state && <FarmerList farmers={list} onEdit={setFarmerForm} onOpen={setOpenFarmer} showCampaign title={kind === "suppliers" ? "Suppliers" : "All farmers"} filters={filters}
        empty={all.length ? "No farmer matches these filters." : "No farmers yet. Add one, or upload a CSV."} />}
      <FarmerSheet farmer={openFarmer} state={state} onClose={() => setOpenFarmer(null)} />
      <FarmerForm farmer={farmerForm} onClose={() => setFarmerForm(null)} />
      {allowOpen && <Allowlist state={state} onClose={() => setAllowOpen(false)} />}
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

// The numbers real phone calls (and texts) may reach: the server's list, and the ones added here.
function Allowlist({ state, onClose }) {
  const act = useAct();
  const [phone, setPhone] = useState("");
  const [label, setLabel] = useState("");
  const s = state.settings || {};
  const mine = [...(state.allowed_numbers || [])].sort((a, b) => (a.added_at || "").localeCompare(b.added_at || ""));
  const farmers = new Map(state.farmers.map((f) => [f.id, f]));
  const max = s.web_allowlist_max || 0;
  const add = async () => {
    const r = await act(() => api("/api/allowed-numbers", { body: { phone, label } }), "Number allowed.");
    if (r) { setPhone(""); setLabel(""); }
  };
  return (
    <Dialog open onClose={onClose} title="Phone allowlist" wide>
      <p className="muted" style={{ margin: "8px 0" }}>
        The AI agent only phones (and texts) numbers on this list. {s.allow_any_number ? "The server allows every number right now (REAL_CALL_ALLOWLIST is *)." : ""}
      </p>
      <ul className="fs-list">
        {(s.server_allowlist || []).map((n) => (
          <li key={n} className="row"><span className="name">{maskPhone(n)}</span><span className="small muted">set on the server</span></li>
        ))}
        {mine.map((n) => (
          <li key={n.id} className="row">
            <span className="name">{maskPhone(n.phone)}<small className="muted"> · {n.label || farmers.get(n.farmer_id)?.name || "no name"} · added by {n.added_by}</small></span>
            {can("campaign.run") && <ActButton className="btn sm ghost" busy="Removing…" run={() => act(() => api(`/api/allowed-numbers/${n.id}`, { method: "DELETE" }), "Number removed.")}>Remove</ActButton>}
          </li>
        ))}
        {!mine.length && !(s.server_allowlist || []).length && <li className="row muted">No numbers yet.</li>}
      </ul>
      {max > 0 ? (
        <div className="grid3" style={{ alignItems: "end", marginTop: 12 }}>
          <label className="field">Phone number<input type="text" inputMode="tel" placeholder="+62 812 0000 5001" value={phone} onChange={(e) => setPhone(e.target.value)} /></label>
          <label className="field">Name (optional)<input type="text" maxLength={60} value={label} onChange={(e) => setLabel(e.target.value)} /></label>
          <ActButton className="btn solid" busy="Adding…" disabled={!can("campaign.run") || phone.replace(/\D/g, "").length < 7 || mine.length >= max} run={add}>Allow number</ActButton>
        </div>
      ) : <p className="small muted">Adding numbers here is turned off on the server (WEB_ALLOWLIST_MAX=0).</p>}
      <p className="small muted" style={{ marginTop: 10 }}>{mine.length} of {max} numbers added here. A number that belongs to a farmer is linked to them.</p>
      <DialogClose>Close</DialogClose>
    </Dialog>
  );
}
