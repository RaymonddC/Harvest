import { useState } from "react";
import { api, can, plainPrice } from "../../lib.js";
import { useLive } from "../../live.jsx";
import { useAct } from "../../toast.jsx";
import { ActButton, Dialog, DialogClose } from "../../ui.jsx";

// Where the market price comes from. In Indonesia the provincial plantation office (Dinas Perkebunan) publishes the
// farmgate price for palm fruit (TBS), usually every week or two. The planner records it here with its source; the
// price range can follow it, the lowest and highest prices moving with it.
export default function OfficialPrice({ l, crop }) {
  const act = useAct();
  const prices = useLive().state?.official_prices;
  const [open, setOpen] = useState(false);
  const mine = (prices || []).filter((p) => p.crop === crop).sort((a, b) => b.valid_from.localeCompare(a.valid_from));
  const latest = mine.find((p) => !l?.official_province || p.province.toLowerCase() === l.official_province.toLowerCase());
  const [f, setF] = useState({ province: latest?.province || "Riau", valid_from: new Date().toISOString().slice(0, 10), price: "", source: "", url: "" });
  const editable = can("limits.edit");
  if (!l) return null;
  const follow = (enabled) => act(() => api(`/api/limits/${crop}/follow-official`, { method: "PUT", body: { enabled, province: latest?.province || f.province } }),
    enabled ? "The price range now follows the official price." : "The price range no longer follows the official price.");
  const add = async () => {
    const r = await act(() => api("/api/official-prices", { body: { crop, province: f.province, valid_from: f.valid_from, price_per_kg: Number(f.price), source: f.source, url: f.url } }),
      l.follows_official ? "Official price saved; the price range moved with it." : "Official price saved.");
    if (r) { setOpen(false); setF({ ...f, price: "", source: "", url: "" }); }
  };
  return (
    <div className="official">
      <div className="official-line">
        <span className="small">
          {latest ? <>Official price <b>{plainPrice(latest.price_per_kg, l.currency)}</b> ({latest.province}, from {latest.valid_from}{latest.source ? `, ${latest.source}` : ""})</> : "No official price recorded yet."}
          {latest?.url && <>, <a href={latest.url} target="_blank" rel="noopener">source</a></>}
        </span>
        <span className="official-acts">
          {latest && (
            <label className="small" style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={!!l.follows_official} disabled={!editable} onChange={(e) => follow(e.target.checked)} /> Market price follows it
            </label>
          )}
          <button type="button" className="btn sm" disabled={!editable} onClick={() => setOpen(true)}>Record official price</button>
        </span>
      </div>
      <Dialog open={open} onClose={() => setOpen(false)} title="Record the official price">
        <p className="muted" style={{ margin: "8px 0" }}>
          The farmgate price the provincial plantation office (Dinas Perkebunan) publishes, for mature trees. When the market price follows it, the lowest and highest prices move with it by the same percentage.
        </p>
        <div className="grid2" style={{ gap: 10 }}>
          <label className="field">Province<input type="text" value={f.province} onChange={(e) => setF({ ...f, province: e.target.value })} /></label>
          <label className="field">Valid from<input type="date" value={f.valid_from} onChange={(e) => setF({ ...f, valid_from: e.target.value })} /></label>
          <label className="field">Price per kg ({l.currency})<input type="text" inputMode="decimal" className="num-input" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value.replace(/[^0-9.]/g, "") })} /></label>
          <label className="field">Source<input type="text" placeholder="e.g. Disbun Riau, period I October" value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} /></label>
        </div>
        <label className="field" style={{ marginTop: 10 }}>Link (optional)<input type="url" placeholder="https://" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></label>
        {mine.length > 0 && (
          <details style={{ marginTop: 10 }}>
            <summary className="small">Earlier official prices ({mine.length})</summary>
            <ul className="fs-list">{mine.slice(0, 8).map((p) => <li key={p.id} className="row"><span className="name">{p.valid_from}, {p.province}</span><span className="num">{plainPrice(p.price_per_kg, l.currency)}</span></li>)}</ul>
          </details>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <ActButton className="btn solid" busy="Saving…" disabled={!(Number(f.price) > 0) || !f.province.trim()} run={add}>Save</ActButton>
          <DialogClose>Cancel</DialogClose>
        </div>
      </Dialog>
    </div>
  );
}
