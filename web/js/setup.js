import { act, api, avatar, cfg, cropLabel, el, fmtKg, icon, maskPhone, mountShell, plainPrice, subscribe } from "./data.js";

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
form.oninput = () => { limitsDirty = true; drawLadder(); if (state) renderSteps(); };
form.onsubmit = (e) => {
  e.preventDefault();
  const crop = currentLimits().id;
  const body = Object.fromEntries([...new FormData(form)].map(([k, v]) => [k, Number(v)]));
  act(() => api(`/api/limits/${crop}`, { method: "PUT", body }), () => { limitsDirty = false; renderSteps(); return "Price range saved. The agent uses it from the next offer."; });
};

const currentLimits = () => state.limits[0];

function render() {
  shell.update(state);
  renderFarmers();
  renderLimits();
  renderCampaign();
  renderSteps();
}

// Step states in words: farmers loaded, price range saved, calling.
function renderSteps() {
  const farmers = state.farmers.filter((f) => f.type !== "supplier").length;
  const priced = !!currentLimits() && !limitsDirty;
  const c = state.campaigns.find((x) => x.id === "current") || {};
  const running = c.status === "running";
  const mark = (n, done, word) => {
    $(`state-${n}`).className = `pill ${done ? "mint" : ""}`;
    $(`state-${n}`).textContent = word;
    const dot = $(`dot-${n}`);
    if (dot) dot.replaceChildren(done ? icon("check", 16) : String(n));
  };
  mark(1, farmers > 0, farmers > 0 ? "Done" : "To do");
  mark(2, priced, limitsDirty ? "Unsaved" : priced ? "Done" : "To do");
  $("state-3").className = `pill ${running ? "leaf" : ""}`;
  $("state-3").textContent = running ? "Calling" : "Ready";
  const chip = (text, cls) => el("span", { class: `pill lg ${cls}` }, text);
  $("steps").replaceChildren(
    chip(farmers > 0 ? "1 Farmers ✓" : "1 Farmers", farmers > 0 ? "mint" : ""),
    chip(priced ? "2 Price range ✓" : "2 Price range", priced ? "mint" : ""),
    chip(running ? "3 Calling" : "3 Start calling", "now"));
}

function renderFarmers() {
  const q = $("search").value.trim().toLowerCase();
  const farmers = state.farmers.filter((f) => f.type !== "supplier")
    .sort((a, b) => Number(!!b.to_call) - Number(!!a.to_call) || a.id.localeCompare(b.id));
  const rows = farmers.filter((f) => !q || `${f.name} ${f.village}`.toLowerCase().includes(q));
  $("farmer-count").textContent = `${farmers.length} farmers loaded`;
  const langs = [...new Set(farmers.map((f) => f.language).filter(Boolean))];
  const toCall = farmers.filter((f) => f.to_call).length;
  $("farmer-total").textContent = farmers.length ? `${farmers.length} farmers loaded` : "No farmers yet";
  $("farmer-meta").textContent = farmers.length
    ? `${toCall} to call this week · ${langs.join(", ") || "language not set"} · synthetic data`
    : "Upload a CSV with name, phone, crop and language.";
  const tones = ["", "grey", "ink"];
  $("avatars").replaceChildren(...farmers.slice(0, 3).map((f, i) => avatar(f.name, tones[i])),
    ...(farmers.length > 3 ? [el("span", { class: "avatar ink" }, `+${farmers.length - 3}`)] : []));
  $("farmer-rows").replaceChildren(...rows.slice(0, shown).map((f) => el("tr", {},
    el("td", { style: "padding-left:22px" }, el("div", { class: "who-cell" }, avatar(f.name, "sm"),
      el("div", {}, el("b", {}, f.name), el("span", {}, f.village || "")))),
    el("td", { class: "num" }, maskPhone(f.phone)),
    el("td", {}, f.language),
    el("td", {}, cropLabel(f.crop)),
    el("td", { class: "r num" }, f.usual_kg_week ? fmtKg(f.usual_kg_week) : "–"),
    el("td", { class: "r", style: "padding-right:22px" }, el("button", { class: "btn sm",
      onclick: () => act(() => api(`/api/farmers/${f.id}/call`, { body: {} }), `Call to ${f.name} queued. Answer it in the call client.`) }, "Call now")))));
  $("showing").textContent = rows.length
    ? `Showing ${Math.min(shown, rows.length)} of ${rows.length}. Phone numbers are masked on screen.`
    : "No farmer matches that search.";
  $("more").hidden = shown >= rows.length;
}

function renderLimits() {
  const l = currentLimits();
  if (!l) return;
  $("limits-sub").textContent = `${cropLabel(l.crop)}, ${l.currency} per ${l.unit}. The agent can only offer inside this range, and farmers are never offered less than the lowest price.`;
  $("ref-source").textContent = l.reference_source ? `Market price source: ${l.reference_source}` : "";
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
  if (ceil > floor) $("range-ref").style.left = `${Math.min(Math.max((ref - floor) / (ceil - floor), 0), 1) * 100}%`;
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
  const stat = (value, label) => el("div", {}, el("b", {}, value), el("span", {}, label));
  $("campaign-lines").replaceChildren(
    stat(String(toCall.length), toCall.length === 1 ? "farmer" : "farmers"),
    stat(`≤ ${minutes} min`, "per call"),
    stat(retries === 1 ? "1 retry" : `${retries} retries`, "if dropped"));
  $("campaign-sub").textContent = `The agent asks every farmer about weeks 1 to ${s.weeks || 5}, in ${s.language || cfg.language || "the configured language"}.`;
  const running = c.status === "running";
  $("campaign-actions").replaceChildren(...(running ? [
    el("span", { class: "pill lg dot running", style: "align-self:flex-start;background:var(--ink-2);color:var(--on-ink)" }, c.kind === "gap_fill" ? "Gap-fill calls running" : "Calling farmers now"),
    el("a", { class: "btn mint big block", href: "call.html", target: "_blank", rel: "noopener" }, "Open call client"),
    el("button", { class: "btn on-ink block", onclick: () => act(() => api("/api/campaign/stop"), "Calling stopped.") }, "Stop calling"),
  ] : [
    el("button", { class: "btn mint big block", disabled: !toCall.length, onclick: async () => {
      const r = await act(() => api("/api/campaign/start", { body: { kind: "collect" } }));
      if (r) location.href = "index.html";
    } }, icon("phone", 18), toCall.length ? `Start calling ${toCall.length} farmers` : "Add farmers to start"),
  ]));
}

subscribe((s) => { state = s; render(); }, (s) => shell.status(s));
