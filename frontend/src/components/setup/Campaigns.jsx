import { useState } from "react";
import { campaignsOf, CROPS, cropName, multiCrop, useCrop, useMembership } from "../../campaigns.jsx";
import { useConfirm } from "../../dialogs.jsx";
import { api, can, fmtT } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton, Dialog, DialogClose, Icon, SubmitButton } from "../../ui.jsx";

const STATUS = { running: "Calling", stopped: "Stopped", done: "Finished", idle: "Not started" };

function statusOf(c) {
  if (c.status !== "running") return { word: STATUS[c.status] || "Not started", cls: "" };
  return { word: c.kind === "gap_fill" ? "Gap-fill calls" : "Calling farmers", cls: "on" };
}

// One tile per campaign; picking a tile sets the campaign the whole app shows. The picked tile has Edit;
// the last tile starts a new campaign (a crop can have several, for example one per area).
export default function Campaigns({ state }) {
  const { cid, setCampaign } = useCrop();
  const { ofFarmer } = useMembership(state);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(null);
  const campaigns = campaignsOf(state);
  const soon = !multiCrop(state);
  const twins = (c) => campaigns.filter((x) => x.crop === c.crop).length > 1;
  return (
    <section className="campaigns" aria-label="Campaigns">
      <div className="camp-list" role="group" aria-label="Pick a campaign">
        {campaigns.map((c) => {
          const farmers = state.farmers.filter((f) => f.type !== "supplier" && ofFarmer(f) === c.id);
          const toCall = farmers.filter((f) => f.to_call).length;
          const s = statusOf(c);
          const picked = c.id === cid;
          return (
            <div key={c.id} className={`camp ${picked ? "picked" : ""}`}>
              <button type="button" className="camp-pick" aria-pressed={picked} onClick={() => setCampaign(c.id)}>
                <span className="camp-top">
                  <span className="camp-crop"><Icon name="leaf" size={16} />{c.label}</span>
                  <span className={`camp-status ${s.cls}`}><i />{s.word}</span>
                </span>
                {(c.name || twins(c)) && <span className="camp-sub">{cropName(c.crop)}</span>}
                <span className="camp-figs">
                  <span><b className="num">{fmtT(c.target_kg_per_week || 0)} t</b> a week · {c.weeks || 5} weeks</span>
                  <span>{farmers.length} farmers · {toCall} to call</span>
                </span>
              </button>
              {picked && can("campaign.run") && (
                <button type="button" className="camp-edit" onClick={() => setEditing(c)} aria-label={`Edit ${c.label}`}>
                  <Icon name="edit" size={14} />Edit
                </button>
              )}
            </div>
          );
        })}
        <button type="button" className="camp new" onClick={() => setAdding(true)} disabled={!can("campaign.run")}>
          <span className="camp-plus" aria-hidden="true">+</span>
          <span><b>New campaign</b><small>{soon ? "Turned off on this server (MULTI_CROP)" : "Any crop, its own target and farmers"}</small></span>
        </button>
      </div>
      {adding && <NewCampaign onClose={() => setAdding(false)} state={state} soon={soon} onMade={setCampaign} ofFarmer={ofFarmer} />}
      {editing && <EditCampaign c={editing} onClose={() => setEditing(null)} state={state} />}
    </section>
  );
}

// Whole numbers only, typed into plain text boxes (no up and down arrows, a number keypad on phones).
const digitsOnly = (v) => v.replace(/[^0-9]/g, "");

function Fields({ f, setF }) {
  const weeksBad = f.weeks !== "" && (Number(f.weeks) < 1 || Number(f.weeks) > 12);
  const targetBad = f.target !== "" && Number(f.target) < 1;
  return (
    <>
      <label className="field">Name <small className="muted">(optional, for example the area)</small>
        <input type="text" maxLength={60} placeholder="e.g. Palm, Kampar" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
      </label>
      <div className="grid2">
        <label className={`field ${targetBad ? "invalid" : ""}`}>Weekly target, tonnes
          <input type="text" inputMode="numeric" autoComplete="off" required placeholder="e.g. 40" className="num-input"
            value={f.target} onChange={(e) => setF({ ...f, target: digitsOnly(e.target.value) })} aria-invalid={targetBad} />
          {targetBad && <span className="field-err">Must be at least 1 t.</span>}
        </label>
        <label className={`field ${weeksBad ? "invalid" : ""}`}>Weeks to plan
          <input type="text" inputMode="numeric" autoComplete="off" required className="num-input"
            value={f.weeks} onChange={(e) => setF({ ...f, weeks: digitsOnly(e.target.value) })} aria-invalid={weeksBad} />
          {weeksBad && <span className="field-err">Between 1 and 12 weeks.</span>}
        </label>
      </div>
    </>
  );
}
const fieldsOk = (f) => Number(f.target) >= 1 && Number(f.weeks) >= 1 && Number(f.weeks) <= 12;

// Crop, name, weekly target, weeks, and which farmers of that crop join it (those in no campaign are ticked).
function NewCampaign({ onClose, state, soon, onMade, ofFarmer }) {
  const act = useAct();
  const camps = campaignsOf(state);
  const [f, setF] = useState({ crop: "palm", name: "", target: "", weeks: String(state.settings?.weeks || 5) });
  const [picked, setPicked] = useState(null); // null: the default ticks (farmers in no campaign)
  const [saving, setSaving] = useState(false);
  const farmers = state.farmers.filter((x) => x.crop === f.crop && x.type !== "supplier").sort((a, b) => a.name.localeCompare(b.name));
  const ticked = picked ?? new Set(farmers.filter((x) => !ofFarmer(x)).map((x) => x.id));
  const toggle = (id) => { const n = new Set(ticked); if (n.has(id)) n.delete(id); else n.add(id); setPicked(n); };
  const campLabel = (id) => camps.find((c) => c.id === id)?.label;
  const save = async (e) => {
    e.preventDefault();
    if (soon) return;
    setSaving(true);
    const made = await act(() => api("/api/campaigns", { body: { crop: f.crop, name: f.name || null, target_kg_per_week: Number(f.target) * 1000,
      weeks: Number(f.weeks), farmer_ids: [...ticked] } }), (r) => `${r.name || cropName(r.crop)} campaign created.`);
    setSaving(false);
    if (made) { onMade(made.id); onClose(); }
  };
  return (
    <Dialog open onClose={onClose} title="New campaign" wide>
      <form onSubmit={save}>
        <div style={{ display: "grid", gap: 10, margin: "12px 0" }}>
          <label className="field">Crop
            <select value={f.crop} onChange={(e) => { setF({ ...f, crop: e.target.value }); setPicked(null); }}>
              {CROPS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
          </label>
          <Fields f={f} setF={setF} />
          <fieldset className="pick-farmers">
            <legend>Farmers in this campaign <small className="muted">({ticked.size} of {farmers.length} {cropName(f.crop)} farmers)</small></legend>
            {farmers.length ? (
              <ul>
                {farmers.map((x) => {
                  const now = ofFarmer(x);
                  return (
                    <li key={x.id}><label>
                      <input type="checkbox" checked={ticked.has(x.id)} onChange={() => toggle(x.id)} />
                      <span>{x.name}<small className="muted">{x.village ? ` · ${x.village}` : ""}{now ? ` · now in ${campLabel(now)}` : ""}</small></span>
                    </label></li>
                  );
                })}
              </ul>
            ) : <p className="muted small">No {cropName(f.crop)} farmers in the database yet. Add them on the Farmers page, or create the campaign and add them after.</p>}
            <p className="small muted" style={{ margin: 0 }}>A farmer is in one campaign at a time: ticking one from another campaign moves them here.</p>
          </fieldset>
          <p className="sub" style={{ margin: 0 }}>Set the fair price range for {cropName(f.crop)} on the Campaign page before calling. Campaigns of the same crop share it.</p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <SubmitButton busy={saving} disabled={soon || !fieldsOk(f)} busyText="Creating…">Create campaign</SubmitButton>
          <DialogClose>Cancel</DialogClose>
        </div>
      </form>
    </Dialog>
  );
}

// Rename, change the target or weeks, or remove the campaign (its farmers stay in the database).
function EditCampaign({ c, onClose, state }) {
  const act = useAct();
  const confirm = useConfirm();
  const [f, setF] = useState({ name: c.name || "", target: String(Math.round((c.target_kg_per_week || 0) / 1000)), weeks: String(c.weeks || 5) });
  const [saving, setSaving] = useState(false);
  const only = campaignsOf(state).length <= 1;
  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    const ok = await act(() => api(`/api/campaigns/${encodeURIComponent(c.id)}`, { method: "PUT",
      body: { name: f.name, target_kg_per_week: Number(f.target) * 1000, weeks: Number(f.weeks) } }), "Campaign saved.");
    setSaving(false);
    if (ok) onClose();
  };
  const remove = async () => {
    if (await confirm({ title: `Remove ${c.label}?`, body: "Its farmers stay in the farmer database, in no campaign. Past calls and offers stay.", confirm: "Remove campaign", danger: true })) {
      const ok = await act(() => api(`/api/campaigns/${encodeURIComponent(c.id)}`, { method: "DELETE" }), (r) => `Campaign removed; ${r.farmers_freed} farmers are back in the database.`);
      if (ok) onClose();
    }
  };
  return (
    <Dialog open onClose={onClose} title={`Edit ${c.label}`}>
      <form onSubmit={save}>
        <div style={{ display: "grid", gap: 10, margin: "12px 0" }}>
          <p className="sub" style={{ margin: 0 }}>Crop: {cropName(c.crop)} (fixed). Changing the target or weeks redraws the forecast straight away.</p>
          <Fields f={f} setF={setF} />
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <SubmitButton busy={saving} disabled={!fieldsOk(f)} busyText="Saving…">Save</SubmitButton>
          <DialogClose>Cancel</DialogClose>
          <ActButton className="btn ghost danger-text" busy="Removing…" style={{ marginLeft: "auto" }} disabled={only || c.status === "running"}
            title={only ? "The only campaign cannot be removed" : c.status === "running" ? "Stop calling first" : undefined} run={remove}>Remove campaign…</ActButton>
        </div>
      </form>
    </Dialog>
  );
}
