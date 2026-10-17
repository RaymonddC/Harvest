import * as Menu from "@radix-ui/react-dropdown-menu";
import { useState } from "react";
import { campaignsOf, useMembership } from "../../campaigns.jsx";
import { api, can, cropLabel, fmtKg, maskPhone, numberAllowed } from "../../lib.js";
import { useConfirm } from "../../dialogs.jsx";
import { useLive } from "../../live.jsx";
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

// Moves a farmer into another campaign of their crop, or out of every campaign (to: "").
export async function moveFarmer(act, f, from, to, label) {
  if (to) return act(() => api(`/api/campaigns/${encodeURIComponent(to)}/farmers`, { method: "PUT", body: { add: [f.id] } }), `${f.name} moved to ${label}.`);
  return act(() => api(`/api/campaigns/${encodeURIComponent(from)}/farmers`, { method: "PUT", body: { remove: [f.id] } }), `${f.name} is now in no campaign.`);
}

// A list of farmers: search, sort, pages; Call now on each row, Edit and Delete in its "⋯" menu.
// showCampaign: a Campaign column to move each farmer (the farmer database). cid: the campaign this list
// belongs to, which adds "Remove from campaign". filters: extra controls next to the search box.
// "Call phone" (a real Twilio call) appears next to it only when the backend has phone calls switched on;
// "Call now" then becomes "Browser call" (the demo, answered in the call client).
export default function FarmerList({ farmers, onEdit, onOpen, title = "Farmers", cid, showCampaign, filters, empty }) {
  const confirm = useConfirm();
  const act = useAct();
  const { state } = useLive();
  const phoneCalls = !!state?.settings?.phone_calls;
  const { ofFarmer } = useMembership(state);
  const camps = campaignsOf(state);
  const labelOf = (id) => camps.find((c) => c.id === id)?.label || "";
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState({ key: null, dir: 1 });
  const needle = q.trim().toLowerCase();
  let rows = farmers.filter((f) => !needle || `${f.name} ${f.village}`.toLowerCase().includes(needle));
  const col = [...COLUMNS, { key: "campaign", value: (f) => labelOf(ofFarmer(f)) }].find((c) => c.key === sort.key);
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
  const dial = async (f) => {
    const allowed = numberAllowed(state, f.phone);
    const body = allowed
      ? `This places a real phone call to ${maskPhone(f.phone)}. The AI agent talks to whoever answers.`
      : `${maskPhone(f.phone)} is not on the real-call allowlist yet. Allowing it lets the agent phone this number (and send texts to it) from now on. The AI agent talks to whoever answers.`;
    if (await confirm({ title: `Call ${f.name}'s phone?`, body, confirm: allowed ? "Call by phone" : "Allow and call" })) {
      act(async () => {
        if (!allowed) await api("/api/allowed-numbers", { body: { phone: f.phone, label: f.name, farmer_id: f.id } });
        return api(`/api/farmers/${f.id}/dial`, { body: {} });
      }, `Calling ${f.name}'s phone…`);
    }
  };
  const remove = async (f) => {
    if (await confirm({ title: `Delete ${f.name}?`, body: "Their waiting calls are withdrawn. Past calls and offers stay.", confirm: "Delete farmer", danger: true })) {
      act(() => api(`/api/farmers/${f.id}`, { method: "DELETE" }), `${f.name} deleted.`);
    }
  };

  return (
    <section className="card" id="farmer-list" aria-labelledby="list-title" style={{ padding: 0, gap: 0 }}>
      <div className="card-head" style={{ padding: "18px 22px", borderBottom: "1px solid var(--line-2)" }}>
        <div><h2 id="list-title">{title}</h2><div className="sub">{farmers.length} {farmers.length === 1 ? "farmer" : "farmers"}</div></div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {filters}
          <input type="search" placeholder="Search name or village" aria-label="Search farmers" style={{ width: 220 }}
            value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        </div>
      </div>
      <div className="table-wrap">
        <table className="farmers" style={{ minWidth: 680 }}>
          <thead>
            <tr>
              <SortHead col={COLUMNS[0]} sort={sort} setSort={sortBy} style={{ paddingLeft: 22 }} />
              <th>Phone</th>
              <SortHead col={COLUMNS[1]} sort={sort} setSort={sortBy} />
              <SortHead col={COLUMNS[2]} sort={sort} setSort={sortBy} />
              {showCampaign && <SortHead col={{ key: "campaign", label: "Campaign" }} sort={sort} setSort={sortBy} />}
              {showCampaign && <th>Plot</th>}
              <SortHead col={COLUMNS[3]} sort={sort} setSort={sortBy} className="r" />
              <th style={{ paddingRight: 22 }}><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody id="farmer-rows">
            {rows.slice(first, first + PAGE).map((f) => (
              <tr key={f.id}>
                <td style={{ paddingLeft: 22 }}><button type="button" className="who-cell who-link" onClick={() => onOpen?.(f)} aria-label={`Open ${f.name}`}><Avatar name={f.name} cls="sm" /><div><b>{f.name}</b><span>{f.village || ""}</span></div></button></td>
                <td className="num">{maskPhone(f.phone)}</td>
                <td>{f.language}</td>
                <td>{cropLabel(f.crop)}</td>
                {showCampaign && (
                  <td>
                    {f.type === "supplier" ? <span className="muted small">Supplier · every {cropLabel(f.crop)} campaign</span> : (
                      <select className="cell-select" aria-label={`Campaign of ${f.name}`} value={ofFarmer(f) || ""} disabled={!can("farmers.manage")}
                        onChange={(e) => moveFarmer(act, f, ofFarmer(f), e.target.value, labelOf(e.target.value))}>
                        <option value="">No campaign</option>
                        {camps.filter((c) => c.crop === f.crop).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                      </select>
                    )}
                  </td>
                )}
                {showCampaign && (
                  <td>{f.plot_lat != null && f.plot_lng != null
                    ? <span className="small">{f.plot_ha ? `${f.plot_ha} ha` : "Mapped"}{f.certification ? ` · ${f.certification}` : ""}</span>
                    : <span className="small muted">Not mapped</span>}</td>
                )}
                <td className="r num">{f.usual_kg_week ? fmtKg(f.usual_kg_week) : "–"}</td>
                <td className="r" style={{ paddingRight: 22, whiteSpace: "nowrap" }}>
                  {phoneCalls && <><ActButton need="campaign.run" className="btn sm leaf" busy="Calling…" run={() => dial(f)}>Call phone</ActButton>{" "}</>}
                  <ActButton need="campaign.run" className="btn sm" busy="Queuing…" run={() => act(() => api(`/api/farmers/${f.id}/call`, { body: {} }), `Call to ${f.name} queued. Answer it in the call client.`)}>{phoneCalls ? "Browser call" : "Call now"}</ActButton>{" "}
                  <Menu.Root>
                    <Menu.Trigger asChild><button className="btn sm more" type="button" aria-label={`More for ${f.name}`}>⋯</button></Menu.Trigger>
                    <Menu.Portal>
                      <Menu.Content className="hc-menu" align="end" sideOffset={4}>
                        <Menu.Item className="hc-menu-item" disabled={!can("farmers.manage")} onSelect={() => onEdit(f)}>Edit</Menu.Item>
                        {cid && <Menu.Item className="hc-menu-item" disabled={!can("farmers.manage")} onSelect={() => moveFarmer(act, f, cid, "")}>Remove from campaign</Menu.Item>}
                        <Menu.Item className="hc-menu-item danger" disabled={!can("farmers.manage")} onSelect={() => remove(f)}>Delete…</Menu.Item>
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
        <span className="sub">{rows.length ? `Showing ${first + 1} to ${Math.min(first + PAGE, rows.length)} of ${rows.length}. Phone numbers are masked on screen.` : (farmers.length ? "No farmer matches that search." : empty || "No farmers yet.")}</span>
        <Pager page={current} pages={pages} go={go} />
      </div>
    </section>
  );
}
