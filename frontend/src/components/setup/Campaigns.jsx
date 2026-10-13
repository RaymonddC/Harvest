import { useState } from "react";
import { campaignsOf, CROPS, cropName, forCrop, multiCrop, useCrop } from "../../campaigns.jsx";
import { api, fmtT } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { Dialog, DialogClose, Icon, SubmitButton } from "../../ui.jsx";

const STATUS = { running: "Calling", stopped: "Stopped", idle: "Not started" };

function statusOf(c) {
  if (c.status !== "running") return { word: STATUS[c.status] || "Not started", cls: "" };
  return { word: c.kind === "gap_fill" ? "Gap-fill calls" : "Calling farmers", cls: "on" };
}

// One tile per campaign; picking a tile sets the crop the whole app shows. The last tile starts a
// new campaign (a preview until the backend supports more than one, see campaigns.jsx).
export default function Campaigns({ state }) {
  const { crop, setCrop } = useCrop();
  const [adding, setAdding] = useState(false);
  const campaigns = campaignsOf(state);
  const soon = !multiCrop(state);
  return (
    <section className="campaigns" aria-label="Campaigns">
      <div className="camp-list" role="group" aria-label="Pick a campaign">
        {campaigns.map((c) => {
          const farmers = forCrop(state.farmers, c.crop).filter((f) => f.type !== "supplier");
          const toCall = farmers.filter((f) => f.to_call).length;
          const s = statusOf(c);
          return (
            <button key={c.id} type="button" className={`camp ${c.crop === crop ? "picked" : ""}`} aria-pressed={c.crop === crop} onClick={() => setCrop(c.crop)}>
              <span className="camp-top">
                <span className="camp-crop"><Icon name="leaf" size={16} />{cropName(c.crop)}</span>
                <span className={`camp-status ${s.cls}`}><i />{s.word}</span>
              </span>
              <span className="camp-figs">
                <span><b className="num">{fmtT(c.target_kg_per_week || 0)} t</b> a week · {c.weeks || 5} weeks</span>
                <span>{farmers.length} farmers · {toCall} to call</span>
              </span>
            </button>
          );
        })}
        <button type="button" className="camp new" onClick={() => setAdding(true)}>
          <span className="camp-plus" aria-hidden="true">+</span>
          <span><b>New campaign</b><small>{soon ? "Rubber, coffee and more · coming soon" : "Another crop, with its own target"}</small></span>
        </button>
      </div>
      <NewCampaign open={adding} onClose={() => setAdding(false)} state={state} soon={soon} taken={new Set(campaigns.map((c) => c.crop))} onMade={setCrop} />
    </section>
  );
}

// Crop, weekly target and weeks. While the backend runs one campaign this is a preview:
// the form can be filled in, but Create stays off and says why.
function NewCampaign({ open, onClose, state, soon, taken, onMade }) {
  const act = useAct();
  const free = CROPS.filter((c) => !taken.has(c.id));
  const [f, setF] = useState({ crop: "", target: "", weeks: String(state.settings?.weeks || 5) });
  const [saving, setSaving] = useState(false);
  const cropId = f.crop || free[0]?.id || "";
  const save = async (e) => {
    e.preventDefault();
    if (soon) return;
    setSaving(true);
    const made = await act(() => api("/api/campaigns", { body: { crop: cropId, target_kg_per_week: Number(f.target) * 1000, weeks: Number(f.weeks) } }),
      () => `${cropName(cropId)} campaign created.`);
    setSaving(false);
    if (made) { onMade(cropId); onClose(); }
  };
  return (
    <Dialog open={open} onClose={onClose} title="New campaign">
      {soon && (
        <p className="camp-soon" role="note">
          Running more than one crop at a time is coming with the next backend update. This is a preview of the form; nothing is saved yet.
        </p>
      )}
      <form onSubmit={save}>
        <div style={{ display: "grid", gap: 10, margin: "12px 0" }}>
          <label className="field">Crop
            <select value={cropId} onChange={(e) => setF({ ...f, crop: e.target.value })} disabled={!free.length}>
              {free.length ? free.map((c) => <option key={c.id} value={c.id}>{c.label}</option>) : <option>Every crop already has a campaign</option>}
            </select>
          </label>
          <div className="grid2">
            <label className="field">Weekly target, tonnes
              <input type="number" min="1" step="1" required placeholder="e.g. 40" value={f.target} onChange={(e) => setF({ ...f, target: e.target.value })} />
            </label>
            <label className="field">Weeks to plan
              <input type="number" min="1" max="12" step="1" required value={f.weeks} onChange={(e) => setF({ ...f, weeks: e.target.value })} />
            </label>
          </div>
          <p className="sub" style={{ margin: 0 }}>
            The agent calls the {cropName(cropId)} farmers on your list. Set the fair price range for {cropName(cropId)} on this page before calling.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {soon || !free.length
            ? <button className="btn solid" type="submit" disabled title={soon ? "Coming with the next backend update" : undefined}>Create campaign</button>
            : <SubmitButton busy={saving} busyText="Creating…">Create campaign</SubmitButton>}
          <DialogClose>{soon ? "Close" : "Cancel"}</DialogClose>
        </div>
      </form>
    </Dialog>
  );
}
