import { useState } from "react";
import { SEGMENT_WORD } from "./Relationship.jsx";
import { campaignsOf, CROPS, cropName, multiCrop, useCrop, useMembership } from "../../campaigns.jsx";
import { toCallOf } from "../../crm.js";
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
  return (
    <section className="campaigns" aria-label="Campaigns">
      <div className="camp-list" role="group" aria-label="Pick a campaign">
        {campaigns.map((c) => {
          const farmers = state.farmers.filter((f) => f.type !== "supplier" && ofFarmer(f) === c.id);
          const toCall = toCallOf(state, c.id).toCall.length;
          const s = statusOf(c);
          const picked = c.id === cid;
          return (
            <div key={c.id} className={`camp ${picked ? "picked" : ""}`}>
              <button type="button" className="camp-pick" aria-pressed={picked} onClick={() => setCampaign(c.id)}>
                <span className="camp-top">
                  <span className="camp-crop"><Icon name="leaf" size={16} />{c.label}</span>
                  <span className={`camp-status ${s.cls}`}><i />{s.word}</span>
                </span>
                {c.name && c.name !== cropName(c.crop) && <span className="camp-sub">{cropName(c.crop)}</span>}
                <span className="camp-figs">
                  <span><b className="num">{fmtT(c.target_kg_per_week || 0)} t</b> a week, {(({ start, end }) => `${shortDay(start)} – ${shortDay(end)}`)(datesOf(c, state.settings))}</span>
                  <span>{farmers.length} farmers, {toCall} to call</span>
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
const isoDay = (d) => d.toISOString().slice(0, 10);
const addDays = (iso, n) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return isoDay(d); };
const daysBetween = (a, b) => Math.round((new Date(`${b}T00:00:00Z`) - new Date(`${a}T00:00:00Z`)) / 86400000);
export const shortDay = (iso) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
// A campaign's dates: its own, or (older campaigns) week 1 for its number of weeks.
export function datesOf(c, settings) {
  const start = c.start_date || settings?.plan_start || isoDay(new Date());
  return { start, end: c.end_date || addDays(settings?.plan_start || start, 7 * (c.weeks || settings?.weeks || 5) - 1) };
}

function Fields({ f, setF, planStart }) {
  const targetBad = f.target !== "" && Number(f.target) < 1;
  const datesBad = f.start && f.end && f.end < f.start;
  const pastEnd = f.end && planStart && f.end < planStart;
  const shown = f.end && planStart && !datesBad && !pastEnd ? Math.min(12, Math.floor(daysBetween(planStart, f.end) / 7) + 1) : 0;
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
      </div>
      <div className="grid2">
        <label className="field">Starts
          <input type="date" required value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} />
        </label>
        <label className={`field ${datesBad || pastEnd ? "invalid" : ""}`}>Ends
          <input type="date" required value={f.end} min={f.start || undefined} onChange={(e) => setF({ ...f, end: e.target.value })} aria-invalid={datesBad || pastEnd} />
          {datesBad && <span className="field-err">The end is before the start.</span>}
          {pastEnd && !datesBad && <span className="field-err">Must end in week 1 ({shortDay(planStart)}) or later.</span>}
        </label>
      </div>
      <div className="grid3">
        <label className="field">Mill capacity a day, t
          <input type="text" inputMode="decimal" className="num-input" placeholder="e.g. 20" value={f.cap ?? ""} onChange={(e) => setF({ ...f, cap: e.target.value.replace(/[^0-9.]/g, "") })} />
        </label>
        <label className="field">Working days a week
          <select value={f.days ?? "6"} onChange={(e) => setF({ ...f, days: e.target.value })}>{[5, 6, 7].map((n) => <option key={n} value={n}>{n}{n === 6 ? " (Mon to Sat)" : n === 5 ? " (Mon to Fri)" : " (every day)"}</option>)}</select>
        </label>
        <label className="field">Truck load, t
          <input type="text" inputMode="decimal" className="num-input" value={f.truck ?? "8"} onChange={(e) => setF({ ...f, truck: e.target.value.replace(/[^0-9.]/g, "") })} />
        </label>
      </div>
      <p className="small muted" style={{ margin: 0 }}>Palm fruit has to be pressed within a day or two, so the mill's daily capacity shows the days and weeks with more fruit than it can take.</p>
      {shown > 0 && (
        <p className="sub" style={{ margin: 0 }}>
          {shortDay(f.start)} to {shortDay(f.end)}, {daysBetween(f.start, f.end) + 1} days. The forecast shows {shown} week{shown === 1 ? "" : "s"} from {shortDay(planStart)}
          {daysBetween(planStart, f.end) >= 84 ? " (at most 12 weeks ahead)" : ""}{f.start > planStart ? "; weeks before the start are greyed out" : ""}.
        </p>
      )}
    </>
  );
}
// Capacity fields in tonnes on screen, kg for the API (an empty capacity clears it).
const ops = (f) => ({ daily_capacity_kg: f.cap ? Number(f.cap) * 1000 : 0, working_days: Number(f.days || 6), truck_kg: Number(f.truck || 8) * 1000 });
const fieldsOk = (f, planStart) => Number(f.target) >= 1 && f.start && f.end && f.end >= f.start && (!planStart || f.end >= planStart);

// Crop, name, weekly target, start and end dates, and which farmers of that crop join it (those in no campaign are ticked).
function NewCampaign({ onClose, state, soon, onMade, ofFarmer }) {
  const act = useAct();
  const camps = campaignsOf(state);
  const planStart = state.settings?.plan_start;
  const [f, setF] = useState(() => ({ crop: "palm", name: "", target: "", ...((d) => ({ start: d.start, end: d.end }))(datesOf({}, state.settings)) }));
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
      start_date: f.start, end_date: f.end, ...ops(f), farmer_ids: [...ticked] } }), (r) => `${r.name || cropName(r.crop)} campaign created.`);
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
          <Fields f={f} setF={setF} planStart={planStart} />
          <fieldset className="pick-farmers">
            <legend>Farmers in this campaign <small className="muted">({ticked.size} of {farmers.length} {cropName(f.crop)} farmers)</small></legend>
            {farmers.length ? (
              <ul>
                {farmers.map((x) => {
                  const now = ofFarmer(x);
                  return (
                    <li key={x.id}><label>
                      <input type="checkbox" checked={ticked.has(x.id)} onChange={() => toggle(x.id)} />
                      <span>{x.name}<small className="muted">{x.village ? `, ${x.village}` : ""}{now ? `, now in ${campLabel(now)}` : ""}</small></span>
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
          <SubmitButton busy={saving} disabled={soon || !fieldsOk(f, planStart)} busyText="Creating…">Create campaign</SubmitButton>
          <DialogClose>Cancel</DialogClose>
        </div>
      </form>
    </Dialog>
  );
}

// Rename, change the target or dates, or remove the campaign (its farmers stay in the database).
function EditCampaign({ c, onClose, state }) {
  const act = useAct();
  const confirm = useConfirm();
  const planStart = state.settings?.plan_start;
  const [f, setF] = useState(() => ({ name: c.name || "", target: String(Math.round((c.target_kg_per_week || 0) / 1000)), ...datesOf(c, state.settings),
    cap: c.daily_capacity_kg ? String(c.daily_capacity_kg / 1000) : "", days: String(c.working_days || 6), truck: String((c.truck_kg || 8000) / 1000) }));
  const [seg, setSeg] = useState(() => ({ reliability: "", size: "", certified: "", ...(c.segment || {}) }));
  const [saving, setSaving] = useState(false);
  const only = campaignsOf(state).length <= 1;
  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    const ok = await act(() => api(`/api/campaigns/${encodeURIComponent(c.id)}`, { method: "PUT",
      body: { name: f.name, target_kg_per_week: Number(f.target) * 1000, start_date: f.start, end_date: f.end, ...ops(f),
        segment: Object.fromEntries(Object.entries(seg).filter(([, v]) => v)) } }), "Campaign saved.");
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
          <p className="sub" style={{ margin: 0 }}>Crop: {cropName(c.crop)} (fixed). Changing the target or dates redraws the forecast straight away.</p>
          <Fields f={f} setF={setF} planStart={planStart} />
          <fieldset className="seg-fields">
            <legend>Who the agent calls in this campaign</legend>
            <div className="grid3">
              {Object.entries(SEGMENT_WORD).map(([key, words]) => (
                <label key={key} className="field">{{ reliability: "Track record", size: "Size", certified: "Certification" }[key]}
                  <select value={seg[key] || ""} onChange={(e) => setSeg({ ...seg, [key]: e.target.value })}>
                    <option value="">Any</option>
                    {Object.entries(words).map(([v, w]) => <option key={v} value={v}>{w}</option>)}
                  </select>
                </label>
              ))}
            </div>
            <small className="muted">Leave all on Any to call every farmer in the campaign. Farmers with Agent calls off are always yours to call.</small>
          </fieldset>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <SubmitButton busy={saving} disabled={!fieldsOk(f, planStart)} busyText="Saving…">Save</SubmitButton>
          <DialogClose>Cancel</DialogClose>
          <ActButton className="btn ghost danger-text" busy="Removing…" style={{ marginLeft: "auto" }} disabled={only || c.status === "running"}
            title={only ? "The only campaign cannot be removed" : c.status === "running" ? "Stop calling first" : undefined} run={remove}>Remove campaign…</ActButton>
        </div>
      </form>
    </Dialog>
  );
}
