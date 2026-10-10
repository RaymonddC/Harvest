import { useState } from "react";
import { api, cropLabel, fmtKg, maskPhone } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { Avatar } from "../../ui.jsx";

const PAGE = 8;

// Every farmer, searchable, with a button to call one now.
export default function FarmerList({ farmers }) {
  const act = useAct();
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(PAGE);
  const needle = q.trim().toLowerCase();
  const rows = farmers.filter((f) => !needle || `${f.name} ${f.village}`.toLowerCase().includes(needle));
  return (
    <section className="card" id="farmer-list" aria-labelledby="list-title" style={{ padding: 0, gap: 0 }}>
      <div className="card-head" style={{ padding: "18px 22px", borderBottom: "1px solid var(--line-2)" }}>
        <div><h2 id="list-title">All farmers</h2><div className="sub">{farmers.length} farmers loaded</div></div>
        <input type="search" placeholder="Search name or village" aria-label="Search farmers" style={{ width: 240 }}
          value={q} onChange={(e) => { setQ(e.target.value); setShown(PAGE); }} />
      </div>
      <div className="table-wrap">
        <table style={{ minWidth: 680 }}>
          <thead><tr><th style={{ paddingLeft: 22 }}>Farmer</th><th>Phone</th><th>Language</th><th>Crop</th><th className="r">Usual kg / week</th><th style={{ paddingRight: 22 }}><span className="sr-only">Actions</span></th></tr></thead>
          <tbody id="farmer-rows">
            {rows.slice(0, shown).map((f) => (
              <tr key={f.id}>
                <td style={{ paddingLeft: 22 }}><div className="who-cell"><Avatar name={f.name} cls="sm" /><div><b>{f.name}</b><span>{f.village || ""}</span></div></div></td>
                <td className="num">{maskPhone(f.phone)}</td>
                <td>{f.language}</td>
                <td>{cropLabel(f.crop)}</td>
                <td className="r num">{f.usual_kg_week ? fmtKg(f.usual_kg_week) : "–"}</td>
                <td className="r" style={{ paddingRight: 22 }}>
                  <button className="btn sm" onClick={() => act(() => api(`/api/farmers/${f.id}/call`, { body: {} }), `Call to ${f.name} queued. Answer it in the call client.`)}>Call now</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "14px 22px" }}>
        <span className="sub">{rows.length ? `Showing ${Math.min(shown, rows.length)} of ${rows.length}. Phone numbers are masked on screen.` : "No farmer matches that search."}</span>
        {shown < rows.length && <button className="btn sm" type="button" onClick={() => setShown(shown + 40)}>Show more</button>}
      </div>
    </section>
  );
}
