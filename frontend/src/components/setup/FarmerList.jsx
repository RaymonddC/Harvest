import * as Menu from "@radix-ui/react-dropdown-menu";
import { useState } from "react";
import { api, cropLabel, fmtKg, maskPhone } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton, Avatar } from "../../ui.jsx";

const PAGE = 10;
// Sortable columns: header label, value to sort by, and whether it is a number.
const COLUMNS = [
  { key: "name", label: "Farmer", value: (f) => f.name || "" },
  { key: "language", label: "Language", value: (f) => f.language || "" },
  { key: "crop", label: "Crop", value: (f) => cropLabel(f.crop) },
  { key: "kg", label: "Usual kg / week", value: (f) => f.usual_kg_week || 0, num: true },
];

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

// A column header that sorts the list; clicking again reverses it.
function SortHead({ col, sort, setSort, className, style }) {
  const on = sort.key === col.key;
  return (
    <th className={className} style={style} aria-sort={on ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" className={`sort ${on ? "on" : ""}`} onClick={() => setSort({ key: col.key, dir: on ? -sort.dir : col.num ? -1 : 1 })}>
        {col.label}<span aria-hidden="true">{on ? (sort.dir === 1 ? " ↑" : " ↓") : ""}</span>
      </button>
    </th>
  );
}

// Every farmer: search, sort, pages; Call now on each row, Edit and Delete in its "⋯" menu.
export default function FarmerList({ farmers, onEdit }) {
  const act = useAct();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState({ key: null, dir: 1 });
  const needle = q.trim().toLowerCase();
  let rows = farmers.filter((f) => !needle || `${f.name} ${f.village}`.toLowerCase().includes(needle));
  const col = COLUMNS.find((c) => c.key === sort.key);
  if (col) {
    rows = [...rows].sort((a, b) => {
      const x = col.value(a), y = col.value(b);
      return (col.num ? x - y : String(x).localeCompare(String(y))) * sort.dir;
    });
  }
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const current = Math.min(page, pages);
  const first = (current - 1) * PAGE;
  const go = (n) => { setPage(n); document.getElementById("farmer-list").scrollIntoView({ block: "start" }); };
  const sortBy = (s) => { setSort(s); setPage(1); };
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
        <table className="farmers" style={{ minWidth: 680 }}>
          <thead>
            <tr>
              <SortHead col={COLUMNS[0]} sort={sort} setSort={sortBy} style={{ paddingLeft: 22 }} />
              <th>Phone</th>
              <SortHead col={COLUMNS[1]} sort={sort} setSort={sortBy} />
              <SortHead col={COLUMNS[2]} sort={sort} setSort={sortBy} />
              <SortHead col={COLUMNS[3]} sort={sort} setSort={sortBy} className="r" />
              <th style={{ paddingRight: 22 }}><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody id="farmer-rows">
            {rows.slice(first, first + PAGE).map((f) => (
              <tr key={f.id}>
                <td style={{ paddingLeft: 22 }}><div className="who-cell"><Avatar name={f.name} cls="sm" /><div><b>{f.name}</b><span>{f.village || ""}</span></div></div></td>
                <td className="num">{maskPhone(f.phone)}</td>
                <td>{f.language}</td>
                <td>{cropLabel(f.crop)}</td>
                <td className="r num">{f.usual_kg_week ? fmtKg(f.usual_kg_week) : "–"}</td>
                <td className="r" style={{ paddingRight: 22, whiteSpace: "nowrap" }}>
                  <ActButton className="btn sm" busy="Queuing…" run={() => act(() => api(`/api/farmers/${f.id}/call`, { body: {} }), `Call to ${f.name} queued. Answer it in the call client.`)}>Call now</ActButton>{" "}
                  <Menu.Root>
                    <Menu.Trigger asChild><button className="btn sm more" type="button" aria-label={`More for ${f.name}`}>⋯</button></Menu.Trigger>
                    <Menu.Portal>
                      <Menu.Content className="hc-menu" align="end" sideOffset={4}>
                        <Menu.Item className="hc-menu-item" onSelect={() => onEdit(f)}>Edit</Menu.Item>
                        <Menu.Item className="hc-menu-item danger" onSelect={() => remove(f)}>Delete…</Menu.Item>
                      </Menu.Content>
                    </Menu.Portal>
                  </Menu.Root>
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
