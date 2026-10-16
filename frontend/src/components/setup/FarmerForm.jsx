import { useEffect, useState } from "react";
import { campaignsOf } from "../../campaigns.jsx";
import { api } from "../../lib.js";
import { useLive } from "../../live.jsx";
import { useAct } from "../../toast.jsx";
import { Dialog, DialogClose, SubmitButton } from "../../ui.jsx";

const LANGUAGES = ["Bahasa Indonesia", "Bahasa Malaysia", "English", "Javanese", "Sundanese", "Thai", "Vietnamese", "Filipino"];
const EMPTY = { name: "", phone: "", crop: "palm", language: "Bahasa Indonesia", village: "", usual_kg_week: "", can_pull_forward: false, campaign_id: "" };

// Add a farmer (farmer = {}, or { crop, campaign_id } to start in a campaign) or edit one (farmer = the record);
// null keeps it closed. Moving an existing farmer between campaigns is done on the Farmers or Campaign page.
export default function FarmerForm({ farmer, onClose }) {
  const act = useAct();
  const { state } = useLive();
  const editing = !!farmer?.id;
  const [f, setF] = useState(EMPTY);
  useEffect(() => {
    if (!farmer) return;
    setF(editing ? {
      name: farmer.name || "", phone: farmer.phone || "", crop: farmer.crop || "palm",
      language: farmer.language || "Bahasa Indonesia", village: farmer.village || "",
      usual_kg_week: farmer.usual_kg_week || "", can_pull_forward: !!farmer.can_pull_forward,
    } : { ...EMPTY, crop: farmer.crop || EMPTY.crop, campaign_id: farmer.campaign_id || "" });
  }, [farmer, editing]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  // An older record may hold a language that is not in the list any more: keep it visible.
  const languages = LANGUAGES.includes(f.language) || !f.language ? LANGUAGES : [...LANGUAGES, f.language];

  const [saving, setSaving] = useState(false);
  const save = async (e) => {
    e.preventDefault();
    const body = { ...f, usual_kg_week: f.usual_kg_week ? Number(f.usual_kg_week) : null };
    if (editing) delete body.campaign_id;
    setSaving(true);
    await act(() => (editing ? api(`/api/farmers/${farmer.id}`, { method: "PUT", body }) : api("/api/farmers", { body })),
      () => { onClose(); return editing ? "Farmer saved." : "Farmer added."; });
    setSaving(false);
  };

  return (
    <Dialog open={!!farmer} onClose={onClose} title={editing ? `Edit ${farmer.name}` : "Add a farmer"}>
      <form id="add-form" onSubmit={save}>
        <div style={{ display: "grid", gap: 10, margin: "12px 0" }}>
          <label className="field">Name <input type="text" required autoComplete="off" value={f.name} onChange={set("name")} /></label>
          <label className="field">Phone <input type="text" inputMode="tel" required placeholder="+62 812 0000 5001" autoComplete="off" value={f.phone} onChange={set("phone")} /></label>
          <label className="field">Crop
            <select value={f.crop} onChange={(e) => setF({ ...f, crop: e.target.value, campaign_id: "" })}><option value="palm">Palm FFB</option><option value="rubber">Rubber</option><option value="coffee">Coffee</option></select>
          </label>
          {!editing && (
            <label className="field">Campaign
              <select value={f.campaign_id} onChange={set("campaign_id")}>
                <option value="">None: the farmer database only</option>
                {campaignsOf(state).filter((c) => c.crop === f.crop).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </label>
          )}
          <label className="field">Language
            <select required value={f.language} onChange={set("language")}>{languages.map((l) => <option key={l}>{l}</option>)}</select>
          </label>
          <label className="field">Village <input type="text" autoComplete="off" value={f.village} onChange={set("village")} /></label>
          <label className="field">Usual kg per week <input type="text" inputMode="numeric" autoComplete="off" placeholder="optional" className="num-input" value={f.usual_kg_week ?? ""}
            onChange={(e) => setF({ ...f, usual_kg_week: e.target.value.replace(/[^0-9]/g, "") })} /></label>
          <label className="field" style={{ flexDirection: "row", gap: 8, alignItems: "center", fontWeight: 400 }}>
            <input type="checkbox" checked={f.can_pull_forward} onChange={set("can_pull_forward")} /> Can bring the harvest forward
          </label>
          <p className="sub" style={{ margin: "-4px 0 0" }}>When a week is short of supply, the agent may ask this farmer to harvest a week or two earlier to fill it. Leave it off if their crop cannot be picked early.</p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <SubmitButton busy={saving} busyText={editing ? "Saving…" : "Adding…"}>{editing ? "Save changes" : "Add farmer"}</SubmitButton>
          <DialogClose>Cancel</DialogClose>
        </div>
      </form>
    </Dialog>
  );
}
