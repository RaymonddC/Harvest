import { useState } from "react";
import { api, cropLabel, fmtKg, maskPhone } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { Avatar } from "../../ui.jsx";

const PAGE = 10;

// Page buttons: Previous, the first and last page, the pages around this one, Next.
function Pager({ page, pages, go }) {
  if (pages <= 1) return null;
  const nums = [...new Set([1, page - 1, page, page + 1, pages])].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  return (
    <nav className="pager" aria-label="Farmer list pages" style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
      <button className="btn sm" type="button" disabled={page === 1} onClick={() => go(page - 1)}>Previous</button>
      {nums.map((n, i) => (
        <span key={n} style={{ display: "contents" }}>
          {i > 0 && n - nums[i - 1] > 1 && <span className="sub">…</span>}
          <button className={`btn sm ${n === page ? "solid" : ""}`} type="button" aria-label={`Page ${n}`}
            aria-current={n === page ? "page" : undefined} onClick={() => go(n)}>{n}</button>
        </span>
      ))}
      <button className="btn sm" type="button" disabled={page === pages} onClick={() => go(page + 1)}>Next</button>
    </nav>
  );
}

// Every farmer, searchable and paged, with Call now, Edit (onEdit) and Delete.
export default function FarmerList({ farmers, onEdit }) {
  const act = useAct();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const needle = q.trim().toLowerCase();
  const rows = farmers.filter((f) => !needle || `${f.name} ${f.village}`.toLowerCase().includes(needle));
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const current = Math.min(page, pages);
  const first = (current - 1) * PAGE;
  const go = (n) => { setPage(n); document.getElementById("farmer-list").scrollIntoView({ block: "start" }); };
  const remove = (f) => {
    if (confirm(`Delete ${f.name}? Their waiting calls are withdrawn. Past calls and offers stay.`)) {
      act(() => api(`/api/farmers/${f.id}`, { method: "DELETE" }), `${f.name} deleted.`);
    }
  };

  return (
    <section className="card" id="farmer-list" aria-labelledby="list-title" style={{ padding: 0, gap: 0 }}>
      <div className="card-head" style={{ padding: "18px 22px", borderBottom: "1px solid var(--line-2)" }}>
        <div><h2 id="list-title">All farmers</h2><div className="sub">{farmers.length} farmers loaded</div></div>
        <input type="search" placeholder="Search name or village" aria-label="Search farmers" style={{ width: 240 }}
          value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      </div>
      <div className="table-wrap">
        <table style={{ minWidth: 680 }}>
          <thead><tr><th style={{ paddingLeft: 22 }}>Farmer</th><th>Phone</th><th>Language</th><th>Crop</th><th className="r">Usual kg / week</th><th style={{ paddingRight: 22 }}><span className="sr-only">Actions</span></th></tr></thead>
          <tbody id="farmer-rows">
            {rows.slice(first, first + PAGE).map((f) => (
              <tr key={f.id}>
                <td style={{ paddingLeft: 22 }}><div className="who-cell"><Avatar name={f.name} cls="sm" /><div><b>{f.name}</b><span>{f.village || ""}</span></div></div></td>
                <td className="num">{maskPhone(f.phone)}</td>
                <td>{f.language}</td>
                <td>{cropLabel(f.crop)}</td>
                <td className="r num">{f.usual_kg_week ? fmtKg(f.usual_kg_week) : "–"}</td>
                <td className="r" style={{ paddingRight: 22, whiteSpace: "nowrap" }}>
                  <button className="btn sm" onClick={() => act(() => api(`/api/farmers/${f.id}/call`, { body: {} }), `Call to ${f.name} queued. Answer it in the call client.`)}>Call now</button>{" "}
                  <button className="btn sm" type="button" onClick={() => onEdit(f)}>Edit</button>{" "}
                  <button className="btn sm" type="button" onClick={() => remove(f)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", padding: "14px 22px" }}>
        <span className="sub">{rows.length ? `Showing ${first + 1} to ${Math.min(first + PAGE, rows.length)} of ${rows.length}. Phone numbers are masked on screen.` : "No farmer matches that search."}</span>
        <Pager page={current} pages={pages} go={go} />
      </div>
    </section>
  );
}
