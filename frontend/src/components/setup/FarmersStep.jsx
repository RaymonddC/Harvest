import { useState } from "react";
import { toast } from "sonner";
import { campaignsOf, cropName, useMembership } from "../../campaigns.jsx";
import { fmtT } from "../../lib.js";
import { unknownSupply } from "./NeedPanel.jsx";
import { api } from "../../lib.js";
import { useLive } from "../../live.jsx";
import { useAct } from "../../toast.jsx";
import { ActButton, Avatar, Dialog, DialogClose, needs } from "../../ui.jsx";
import StepTop from "./StepTop.jsx";

const SAMPLE_CSV = "name,phone,crop,language,village,usual_kg_week,can_pull_forward\nPak Contoh,+62 812 0000 5001,palm,Bahasa Indonesia,Sungai Lala,1500,yes";
const TONES = ["", "grey", "ink"];

// Step 1: who the agent will call in this campaign. New farmers (onAdd), farmers already in the database
// ("Add from database"), or a CSV upload, all land in this campaign.
export default function FarmersStep({ farmers, toCall, onAdd, cid, crop }) {
  const act = useAct();
  const [open, setOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const [csv, setCsv] = useState(SAMPLE_CSV);
  const { state } = useLive();
  const unknown = state ? unknownSupply(state, cid) : { unknown: [], usualKg: 0 };
  const upload = () => act(async () => {
    const r = await api("/api/farmers/upload", { body: { csv, campaign_id: cid } });
    setOpen(false);
    return r;
  }, (r) => {
    // Lines that could not be read are listed in a toast that stays until it is closed, so they can be fixed.
    if (r.skipped?.length) {
      toast.warning(`${r.skipped.length} line${r.skipped.length > 1 ? "s" : ""} skipped`, {
        description: <ul className="skipped">{r.skipped.slice(0, 8).map((x) => <li key={x}>{x}</li>)}</ul>,
        duration: Infinity, closeButton: true });
    }
    return `${r.added} farmers added to this campaign.`;
  });

  return (
    <section className={`card ${farmers.length ? "done" : ""}`} aria-labelledby="farmers-title">
      <StepTop n={1} label="Who" done={farmers.length > 0} word={farmers.length ? "Ready" : "To do"} />
      <div className="step-head"><h2 id="farmers-title">Farmers</h2><span className="sub">Who the agent calls in this campaign.</span></div>
      <div className="drop">
        <div className="stack" id="avatars" aria-hidden="true">
          {farmers.slice(0, 3).map((f, i) => <Avatar key={f.id} name={f.name} cls={TONES[i]} />)}
          {farmers.length > 3 && <span className="avatar ink">+{farmers.length - 3}</span>}
        </div>
        <span className="big">{farmers.length ? `${farmers.length} farmers in this campaign` : "No farmers yet"}</span>
        <span className="sub">{farmers.length
          ? (unknown.unknown.length
            ? <><a href="#farmer-list">{toCall} need a harvest call</a>, {unknown.unknown.length} with no current answer (about {fmtT(unknown.usualKg)} t a week)</>
            : toCall ? <><a href="#farmer-list">{toCall} need a harvest call</a> (unsure answers)</> : <>Every farmer has a current answer</>)
          : `Add ${cropName(crop)} farmers from the database, or new ones.`}</span>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
          <button className="btn" type="button" onClick={() => setPicking(true)} {...needs("farmers.manage")}>Add from database</button>
          <button className="btn" type="button" onClick={onAdd} {...needs("farmers.manage")}>New farmer</button>
          <button className="btn" type="button" onClick={() => setOpen(true)} {...needs("farmers.manage")}>Upload CSV</button>
        </div>
      </div>

      <Dialog open={open} onClose={() => setOpen(false)} title="Upload farmers into this campaign">
        <p className="muted" style={{ margin: "8px 0" }}>
          One farmer per line. Required: name, phone, crop ({cropName(crop)} for this campaign), language (Bahasa Indonesia, Bahasa Malaysia, English, Javanese, Sundanese, Thai, Vietnamese or Filipino).
          Optional: village, usual_kg_week, can_pull_forward (yes or no). A phone already in the database updates that farmer and moves them here.
          <a href="/farmers-template.csv" download> Download the template</a>, fill it in, then choose the file here.
        </p>
        <input type="file" accept=".csv,text/csv" aria-label="CSV file" style={{ marginBottom: 8 }}
          onChange={async (e) => { const f = e.target.files[0]; if (f) setCsv(await f.text()); }} />
        <textarea aria-label="CSV text" value={csv} onChange={(e) => setCsv(e.target.value)} />
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <ActButton className="btn solid" busy="Uploading…" run={upload}>Upload</ActButton>
          <DialogClose>Cancel</DialogClose>
        </div>
      </Dialog>
      {picking && <PickFromDatabase cid={cid} crop={crop} onClose={() => setPicking(false)} />}
    </section>
  );
}

// The crop's farmers who are not in this campaign: tick some and add them (a farmer in another campaign moves).
function PickFromDatabase({ cid, crop, onClose }) {
  const act = useAct();
  const { state } = useLive();
  const { ofFarmer } = useMembership(state);
  const camps = campaignsOf(state);
  const [q, setQ] = useState("");
  const [ticked, setTicked] = useState(new Set());
  const [onlyFree, setOnlyFree] = useState(true);
  const all = (state?.farmers || []).filter((f) => f.crop === crop && f.type !== "supplier" && ofFarmer(f) !== cid);
  const needle = q.trim().toLowerCase();
  const list = all.filter((f) => (!onlyFree || !ofFarmer(f)) && (!needle || `${f.name} ${f.village}`.toLowerCase().includes(needle)))
    .sort((a, b) => a.name.localeCompare(b.name));
  const toggle = (id) => { const n = new Set(ticked); if (n.has(id)) n.delete(id); else n.add(id); setTicked(n); };
  const add = async () => {
    const r = await act(() => api(`/api/campaigns/${encodeURIComponent(cid)}/farmers`, { method: "PUT", body: { add: [...ticked] } }),
      (x) => `${x.added} farmers added to this campaign.`);
    if (r) onClose();
  };
  return (
    <Dialog open onClose={onClose} title="Add farmers from the database" wide>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", margin: "10px 0" }}>
        <input type="search" placeholder="Search name or village" aria-label="Search the farmer database" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: "1 1 200px" }} />
        <label className="small" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={onlyFree} onChange={(e) => setOnlyFree(e.target.checked)} /> Only farmers in no campaign
        </label>
      </div>
      <fieldset className="pick-farmers">
        <legend className="sr-only">{cropName(crop)} farmers</legend>
        {list.length ? (
          <ul>
            {list.map((f) => {
              const now = ofFarmer(f);
              return (
                <li key={f.id}><label>
                  <input type="checkbox" checked={ticked.has(f.id)} onChange={() => toggle(f.id)} />
                  <span>{f.name}<small className="muted">{f.village ? `, ${f.village}` : ""}{now ? `, now in ${camps.find((c) => c.id === now)?.label}` : ""}</small></span>
                </label></li>
              );
            })}
          </ul>
        ) : <p className="muted small">{all.length ? "No farmer matches. Untick \"Only farmers in no campaign\" to see farmers in other campaigns." : `Every ${cropName(crop)} farmer is already in this campaign. Add new ones on the Farmers page.`}</p>}
      </fieldset>
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap", alignItems: "center" }}>
        <ActButton className="btn solid" busy="Adding…" disabled={!ticked.size} run={add}>Add {ticked.size || ""} {ticked.size === 1 ? "farmer" : "farmers"}</ActButton>
        <DialogClose>Cancel</DialogClose>
        <span className="small muted">A farmer is in one campaign at a time; adding one from another campaign moves them.</span>
      </div>
    </Dialog>
  );
}
