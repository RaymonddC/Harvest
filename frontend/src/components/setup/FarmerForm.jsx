import { useEffect, useState } from "react";
import { api } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { Dialog, DialogClose } from "../../ui.jsx";

const LANGUAGES = ["Bahasa Indonesia", "Bahasa Malaysia", "English", "Javanese", "Sundanese"];
const EMPTY = { name: "", phone: "", crop: "palm", language: "Bahasa Indonesia", village: "", usual_kg_week: "", can_pull_forward: false };

// Add a farmer (farmer = {}) or edit one (farmer = the record); null keeps it closed.
export default function FarmerForm({ farmer, onClose }) {
  const act = useAct();
  const editing = !!farmer?.id;
  const [f, setF] = useState(EMPTY);
  useEffect(() => {
    if (!farmer) return;
    setF(editing ? {
      name: farmer.name || "", phone: farmer.phone || "", crop: farmer.crop || "palm",
      language: farmer.language || "Bahasa Indonesia", village: farmer.village || "",
      usual_kg_week: farmer.usual_kg_week || "", can_pull_forward: !!farmer.can_pull_forward,
    } : EMPTY);
  }, [farmer, editing]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  // An older record may hold a language that is not in the list any more: keep it visible.
  const languages = LANGUAGES.includes(f.language) || !f.language ? LANGUAGES : [...LANGUAGES, f.language];

  const save = (e) => {
    e.preventDefault();
    const body = { ...f, usual_kg_week: f.usual_kg_week ? Number(f.usual_kg_week) : null };
    act(() => (editing ? api(`/api/farmers/${farmer.id}`, { method: "PUT", body }) : api("/api/farmers", { body })),
      () => { onClose(); return editing ? "Farmer saved." : "Farmer added."; });
  };

  return (
    <Dialog open={!!farmer} onClose={onClose} title={editing ? `Edit ${farmer.name}` : "Add a farmer"}>
      <form id="add-form" onSubmit={save}>
        <div style={{ display: "grid", gap: 10, margin: "12px 0" }}>
          <label className="field">Name <input type="text" required autoComplete="off" value={f.name} onChange={set("name")} /></label>
          <label className="field">Phone <input type="text" inputMode="tel" required placeholder="+62 812 0000 5001" autoComplete="off" value={f.phone} onChange={set("phone")} /></label>
          <label className="field">Crop
            <select value={f.crop} onChange={set("crop")}><option value="palm">Palm FFB</option><option value="rubber">Rubber</option><option value="coffee">Coffee</option></select>
          </label>
          <label className="field">Language
            <select required value={f.language} onChange={set("language")}>{languages.map((l) => <option key={l}>{l}</option>)}</select>
          </label>
          <label className="field">Village <input type="text" autoComplete="off" value={f.village} onChange={set("village")} /></label>
          <label className="field">Usual kg per week <input type="number" min="0" step="1" placeholder="optional" value={f.usual_kg_week} onChange={set("usual_kg_week")} /></label>
          <label className="field" style={{ flexDirection: "row", gap: 8, alignItems: "center", fontWeight: 400 }}>
            <input type="checkbox" checked={f.can_pull_forward} onChange={set("can_pull_forward")} /> Can bring the harvest forward
          </label>
          <p className="sub" style={{ margin: "-4px 0 0" }}>When a week is short of supply, the agent may ask this farmer to harvest a week or two earlier to fill it. Leave it off if their crop cannot be picked early.</p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn solid" type="submit">{editing ? "Save changes" : "Add farmer"}</button>
          <DialogClose>Cancel</DialogClose>
        </div>
      </form>
    </Dialog>
  );
}
