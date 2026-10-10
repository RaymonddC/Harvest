import { useState } from "react";
import { api } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { Avatar, Dialog, DialogClose } from "../../ui.jsx";
import StepTop from "./StepTop.jsx";

const SAMPLE_CSV = "name,phone,crop,language,village\nPak Contoh,+62 812 0000 5001,palm,Bahasa Indonesia,Sungai Lala";
const TONES = ["", "grey", "ink"];

// Step 1: who the agent will call, and the CSV upload.
export default function FarmersStep({ farmers, toCall }) {
  const act = useAct();
  const [open, setOpen] = useState(false);
  const [csv, setCsv] = useState(SAMPLE_CSV);
  const langs = [...new Set(farmers.map((f) => f.language).filter(Boolean))];
  const upload = () => act(async () => {
    const r = await api("/api/farmers/upload", { body: { csv } });
    setOpen(false);
    return r;
  }, (r) => `${r.added} farmers added.`);

  return (
    <section className="card" aria-labelledby="farmers-title">
      <StepTop n={1} done={farmers.length > 0} word={farmers.length ? "Done" : "To do"} />
      <div className="step-head"><h2 id="farmers-title">Farmers</h2><span className="sub">Who the agent will call.</span></div>
      <div className="drop">
        <div className="stack" id="avatars" aria-hidden="true">
          {farmers.slice(0, 3).map((f, i) => <Avatar key={f.id} name={f.name} cls={TONES[i]} />)}
          {farmers.length > 3 && <span className="avatar ink">+{farmers.length - 3}</span>}
        </div>
        <span className="big">{farmers.length ? `${farmers.length} farmers loaded` : "No farmers yet"}</span>
        <span className="sub">{farmers.length
          ? `${toCall} to call this week · ${langs.join(", ") || "language not set"} · synthetic data`
          : "Upload a CSV with name, phone, crop and language."}</span>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
          <button className="btn" type="button" onClick={() => setOpen(true)}>Upload CSV</button>
          <a className="btn ghost" href="#farmer-list">See the list</a>
        </div>
      </div>

      <Dialog open={open} onClose={() => setOpen(false)} title="Upload farmer list">
        <p className="muted" style={{ margin: "8px 0" }}>CSV with columns name, phone, crop, language. Optional: village, can_pull_forward.</p>
        <input type="file" accept=".csv,text/csv" aria-label="CSV file" style={{ marginBottom: 8 }}
          onChange={async (e) => { const f = e.target.files[0]; if (f) setCsv(await f.text()); }} />
        <textarea aria-label="CSV text" value={csv} onChange={(e) => setCsv(e.target.value)} />
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <button className="btn solid" onClick={upload}>Upload</button>
          <DialogClose>Cancel</DialogClose>
        </div>
      </Dialog>
    </section>
  );
}
