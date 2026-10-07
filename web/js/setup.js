import { act, api, cfg, cropLabel, el, fmtKg, maskPhone, mountShell, plainPrice, subscribe } from "./data.js";

const $ = (id) => document.getElementById(id);
const shell = mountShell("setup");
const PAGE = 8;
let state = null;
let shown = PAGE;
let limitsDirty = false;

$("search").oninput = () => { shown = PAGE; renderFarmers(); };
$("more").onclick = () => { shown += 40; renderFarmers(); };
$("upload-open").onclick = () => $("upload-dialog").showModal();
$("upload-file").onchange = async (e) => { const f = e.target.files[0]; if (f) $("upload-text").value = await f.text(); };
$("upload-send").onclick = () => act(async () => {
  const r = await api("/api/farmers/upload", { body: { csv: $("upload-text").value } });
  $("upload-dialog").close();
  return r;
}, (r) => `${r.added} farmers added.`);
$("reset").onclick = () => act(() => api("/api/demo/reset"), "Demo data reset.");

const form = $("limits-form");
form.oninput = () => { limitsDirty = true; drawLadder(); };
form.onsubmit = (e) => {
  e.preventDefault();
  const crop = currentLimits().id;
  const body = Object.fromEntries([...new FormData(form)].map(([k, v]) => [k, Number(v)]));
  act(() => api(`/api/limits/${crop}`, { method: "PUT", body }), () => { limitsDirty = false; return "Limits saved. The agent uses them from the next offer."; });
};

const currentLimits = () => state.limits[0];

function render() {
  shell.update(state);
  renderFarmers();
  renderLimits();
  renderCampaign();
}

function renderFarmers() {
  const q = $("search").value.trim().toLowerCase();
  const farmers = state.farmers.filter((f) => f.type !== "supplier")
    .sort((a, b) => Number(!!b.to_call) - Number(!!a.to_call) || a.id.localeCompare(b.id));
  const rows = farmers.filter((f) => !q || `${f.name} ${f.village}`.toLowerCase().includes(q));
  $("farmer-count").textContent = `${farmers.length} farmers loaded`;
  $("farmer-rows").replaceChildren(...rows.slice(0, shown).map((f) => el("tr", {},
    el("td", { style: "font-weight:500" }, f.name),
    el("td", {}, f.village),
    el("td", { class: "num" }, maskPhone(f.phone)),
    el("td", {}, f.language),
    el("td", {}, cropLabel(f.crop)),
    el("td", { class: "r num" }, f.usual_kg_week ? fmtKg(f.usual_kg_week) : "–"),
    el("td", { class: "r" }, el("button", { class: "btn", style: "min-height:36px;padding:0 12px;font-size:13px",
      onclick: () => act(() => api(`/api/farmers/${f.id}/call`, { body: {} }), `Call to ${f.name} queued. Answer it in the call client.`) }, "Call now")))));
  $("showing").textContent = rows.length
    ? `Showing ${Math.min(shown, rows.length)} of ${rows.length}. Phone numbers are masked on screen.`
    : "No farmer matches that search.";
  $("more").hidden = shown >= rows.length;
}

function renderLimits() {
  const l = currentLimits();
  if (!l) return;
  $("limits-title").textContent = `Price limits · ${cropLabel(l.crop)}`;
  $("limits-sub").textContent = `${l.currency} per ${l.unit}. Enforced in code; the agent can never offer outside them.`;
  $("ref-source").textContent = l.reference_source ? `Source: ${l.reference_source}` : "";
  $("subtitle").textContent = `Upload farmers, set price limits for ${l.crop === "palm" ? "fresh fruit bunches" : cropLabel(l.crop).toLowerCase()}, then start the call campaign. All data is synthetic.`;
  if (!limitsDirty) {
    for (const k of ["floor_price", "reference_price", "ceiling_price", "first_premium_pct", "step_pct"]) form.elements[k].value = l[k];
  }
  drawLadder();
}

function drawLadder() {
  const l = currentLimits();
  const v = (k) => Number(form.elements[k].value);
  const floor = v("floor_price"), ref = v("reference_price"), ceil = v("ceiling_price");
  const inc = l.price_increment || 0.01;
  const box = $("ladder");
  if (!(floor > 0 && floor <= ref && ref <= ceil) || v("step_pct") <= 0) {
    box.replaceChildren(el("span", {}, "Needs floor ≤ reference ≤ ceiling."));
    return;
  }
  const round = (p) => Math.round(p / inc) * inc;
  const rungs = [];
  for (let p = ref * (1 + v("first_premium_pct") / 100); round(p) < ceil && rungs.length < 30; p += ref * v("step_pct") / 100) {
    const r = Math.max(round(p), floor);
    if (!rungs.length || r > rungs[rungs.length - 1]) rungs.push(r);
  }
  rungs.push(ceil);
  box.replaceChildren(...rungs.map((p) => el("span", { class: "num" }, plainPrice(p, l.currency))));
}

function renderCampaign() {
  const c = state.campaigns.find((x) => x.id === "current") || {};
  const toCall = state.farmers.filter((f) => f.to_call);
  const s = state.settings || {};
  const minutes = Math.round((s.max_call_seconds || 360) / 60);
  const retries = Math.max((s.max_call_attempts || 2) - 1, 0);
  $("campaign-lines").replaceChildren(
    el("span", {}, `${toCall.length} farmers to call · ${s.language || cfg.language || "configured language"}`),
    el("span", {}, `Asks about harvests for weeks 1 to ${s.weeks || 5}`),
    el("span", {}, `Calls end within ${minutes} minutes; a dropped call retries ${retries === 1 ? "once" : `${retries} times`}`),
  );
  const running = c.status === "running";
  $("campaign-actions").replaceChildren(...(running ? [
    el("span", { class: "pill mint dot running", style: "align-self:flex-start" }, c.kind === "gap_fill" ? "Gap-fill calls running" : "Campaign running"),
    el("a", { class: "btn mint big", href: "call.html", target: "_blank", rel: "noopener" }, "Open call client"),
    el("button", { class: "btn on-ink", onclick: () => act(() => api("/api/campaign/stop"), "Campaign stopped.") }, "Stop campaign"),
  ] : [
    el("button", { class: "btn mint big", onclick: async () => {
      const r = await act(() => api("/api/campaign/start", { body: { kind: "collect" } }));
      if (r) location.href = "index.html";
    } }, "Start campaign"),
  ]));
}

subscribe((s) => { state = s; render(); }, (s) => shell.status(s));
