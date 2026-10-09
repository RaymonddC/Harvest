import { act, api, apiUrl, avatar, callChip, cfg, cropLabel, el, fmtPrice, fmtT, icon, KIND_WORD, mountShell, pill, subscribe } from "./data.js";

const $ = (id) => document.getElementById(id);
const shell = mountShell("forecast");
let state = null;
let noteKey = "";
let polishedNote = null;

$("csv").href = apiUrl("/api/forecast.csv");
$("call-log-open").onclick = () => { renderLog(); $("log-dialog").showModal(); };

const byWeek = (a, b) => a.week - b.week;

function render() {
  shell.update(state);
  const rows = [...state.forecast].sort(byWeek);
  const crop = (state.limits[0] && state.limits[0].crop) || "palm";
  $("subtitle").textContent = `Expected ${cropLabel(crop)} per week against the mill's target, updated as each call is saved.`;
  renderCampaign();
  renderKpis(rows);
  renderChart(rows);
  renderNote(rows);
  renderGap(rows);
  renderCalls();
}

function renderCampaign() {
  const c = state.campaigns.find((x) => x.id === "current") || {};
  const running = c.status === "running";
  const p = $("campaign-pill");
  p.className = `pill lg dot ${running ? "mint running" : ""}`;
  p.textContent = running ? (c.kind === "gap_fill" ? "Gap-fill calls running" : "Campaign running") : "No campaign running";
}

function campaignCalls() {
  return state.calls.filter((c) => c.kind !== "confirm" && (c.attempt || 1) === 1);
}

function renderKpis(rows) {
  if (!rows.length) { $("kpis").replaceChildren(); return; }
  const target = rows[0].target_kg;
  const gap = rows.find((r) => r.is_gap);
  const focus = gap || rows.reduce((a, b) => (b.expected_kg < a.expected_kg ? b : a));
  const calls = campaignCalls();
  const done = calls.filter((c) => ["done", "declined"].includes(c.status)).length;
  const kpi = (label, value, cls = "", extra = null) =>
    el("div", { class: `kpi ${cls}` }, el("span", { class: "label" }, label), el("span", { class: "value" }, value), extra);
  $("kpis").replaceChildren(
    kpi("Weekly target", `${fmtT(target)} t`),
    kpi(`Week ${focus.week} expected`, `${fmtT(focus.expected_kg)} t`),
    gap ? kpi(`Week ${gap.week} gap`, `${fmtT(gap.gap_kg)} t short`, "amber")
      : kpi("Gap", "None", "mint"),
    kpi("Calls", calls.length ? el("span", {}, `${done} `, el("small", {}, `of ${calls.length} done`)) : "None yet", "",
      calls.length ? el("div", { class: "bar" }, el("i", { style: `width:${(done / calls.length) * 100}%` })) : null),
  );
}

function renderChart(rows) {
  const area = $("chart-area");
  if (!rows.length) {
    area.replaceChildren(el("div", { class: "empty" }, el("p", {}, "No forecast yet. Start a call campaign to collect harvest answers."),
      el("a", { class: "btn", href: "setup.html" }, "Go to setup")));
    return;
  }
  const target = rows[0].target_kg;
  $("legend-target").textContent = `Target ${fmtT(target)} t`;
  const max = Math.max(target * 1.15, ...rows.map((r) => r.expected_kg + r.pending_kg));
  const pct = (kg) => `${(kg / max) * 100}%`;
  const line = el("div", { class: "target", "data-label": `Target ${fmtT(target)} t` });
  line.style.bottom = pct(target);
  const bars = el("div", { class: "bars" }, rows.map((r) => {
    const col = el("div", { class: `col ${r.is_gap ? "is-gap" : ""}` });
    col.append(el("div", { class: "val num" }, el("span", {}, r.is_gap ? `${fmtT(r.expected_kg)} · ${fmtT(r.gap_kg)} t short` : fmtT(r.expected_kg)),
      r.pending_kg ? el("small", {}, el("span", {}, `+${fmtT(r.pending_kg)} pending`)) : null));
    if (r.pending_kg) {
      const p = el("div", { class: "pend", title: `${fmtT(r.pending_kg)} t waiting for approval` });
      p.style.height = pct(r.pending_kg);
      col.append(p);
    }
    const bar = el("div", { class: `bar ${r.is_gap ? "gap" : ""}` });
    bar.style.height = pct(r.expected_kg);
    col.append(bar);
    return col;
  }));
  const chart = el("div", { class: "chart", role: "img",
    "aria-label": rows.map((r) => `${r.label} ${fmtT(r.expected_kg)} tonnes${r.is_gap ? ", gap" : ""}`).join("; ") }, line, bars);
  const labels = el("div", { class: "xlabels", "aria-hidden": "true" }, rows.map((r) => {
    const d = new Date(r.week_start + "T00:00:00");
    return el("span", { class: r.is_gap ? "gap" : "" }, r.label,
      el("small", {}, d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })));
  }));
  area.replaceChildren(chart, labels);
}

function renderNote(rows) {
  const gap = rows.find((r) => r.is_gap);
  const box = $("gap-note");
  box.hidden = !gap || !gap.note;
  if (!gap || !gap.note) return;
  const key = `${gap.week}:${gap.note}`;
  if (key !== noteKey) {
    noteKey = key;
    polishedNote = null;
    api("/api/forecast/summary", { method: "GET" }).then((r) => {
      if (`${r.gap_week}` === `${gap.week}` && r.gap_note) { polishedNote = r; renderNote([...state.forecast].sort(byWeek)); }
    }).catch(() => {});
  }
  const text = polishedNote ? polishedNote.gap_note : gap.note;
  const by = polishedNote && polishedNote.gap_note_by === "gemini" ? "Note drafted by Gemini." : "Note built from today's call answers.";
  box.replaceChildren(el("span", { class: "spark" }, icon("spark", 15)),
    el("div", {}, el("strong", { style: "display:block" }, `Why week ${gap.week} is short`), text, " ", el("span", { class: "muted" }, by)));
}

function renderGap(rows) {
  const gap = rows.find((r) => r.is_gap);
  $("gap-card").hidden = !gap;
  $("ok-card").hidden = !!gap || !rows.length;
  if (!gap) return;
  const list = gap.shortlist || [];
  const farmersKg = list.reduce((s, p) => s + p.kg, 0);
  const fromWeeks = [...new Set(list.map((p) => p.from_week))].sort().map((w) => `week ${w}`).join(" and ");
  const quotes = state.rival_quotes.filter((q) => q.deliver_week === gap.week);
  const quoteKg = quotes.reduce((s, q) => s + q.kg, 0);
  const used = (q) => state.offers.some((o) => o.source === `rival_quote:${q.id}` && ["pending", "approved"].includes(o.status));
  let text = list.length
    ? `${list.length} farmer${list.length > 1 ? "s" : ""} can bring delivery forward from ${fromWeeks}, about ${fmtT(farmersKg)} t.`
    : "No farmer on record can bring delivery forward.";
  if (quotes.length) text += farmersKg + quoteKg >= gap.gap_kg
    ? ` A rival supplier quote covers the remaining ${fmtT(gap.gap_kg - farmersKg > 0 ? gap.gap_kg - farmersKg : quoteKg)} t.`
    : ` A rival supplier quote covers ${fmtT(quoteKg)} t.`;

  const top = list.slice(0, 3);
  const rest = list.slice(3);
  $("gap-card").replaceChildren(
    el("span", { class: "eyebrow" }, `Gap alert · week ${gap.week}`),
    el("h2", { style: "font-size:22px" }, `${fmtT(gap.gap_kg)} t to fill`),
    el("p", {}, text),
    list.length || quotes.length ? el("div", { class: "list-card" },
      top.map((p) => el("div", { class: "li" }, avatar(p.name, "sm"), el("span", {}, `${p.name}${p.village ? ` · ${p.village}` : ""}`), el("strong", {}, `${fmtT(p.kg)} t`))),
      rest.length ? el("div", { class: "li" }, el("span", { class: "avatar sm grey", "aria-hidden": "true" }, `+${rest.length}`),
        el("span", { class: "muted" }, `${rest.length} more farmer${rest.length > 1 ? "s" : ""}`),
        el("strong", {}, `${fmtT(rest.reduce((s, p) => s + p.kg, 0))} t`)) : null,
      quotes.map((q) => el("div", { class: "li sep" }, avatar(q.supplier_name, "sm ink"),
        el("span", {}, `${q.supplier_name}, quote ${fmtPrice(q.price_per_kg, q.currency || "IDR")}`),
        el("span", { style: "display:flex;gap:8px;align-items:center" },
          used(q) ? pill("Offer added", "mint")
            : el("button", { class: "btn sm",
              onclick: () => act(() => api(`/api/rival-quotes/${q.id}/offer`), "Rival quote added to approvals.") }, "Add as offer"),
          el("strong", {}, `${fmtT(q.kg)} t`))))) : null,
    el("button", { class: "btn leaf big block", disabled: !list.length && !state.farmers.some((f) => f.type === "supplier"),
      onclick: () => act(() => api("/api/campaign/start", { body: { kind: "gap_fill" } }),
        (r) => `${r.queued} gap-fill calls queued. Answer them in the call client.`) }, icon("phone", 16), "Start gap-fill calls"),
  );
}

function renderCalls() {
  const calls = [...state.calls].sort((a, b) => (b.started_at || b.created_at || "").localeCompare(a.started_at || a.created_at || ""));
  const onCall = calls.filter((c) => c.status === "on_call");
  const finished = calls.filter((c) => ["done", "declined", "dropped"].includes(c.status)).slice(0, 5 - Math.min(onCall.length, 4));
  const queued = calls.filter((c) => c.status === "queued");
  const row = (c) => {
    const chip = callChip(c);
    const label = c.kind === "collect" ? c.farmer_name : `${c.farmer_name} · ${KIND_WORD[c.kind].replace(" call", "")}`;
    const av = avatar(c.farmer_name, `sm ${c.status === "on_call" ? "" : "grey"}`);
    return c.status === "on_call"
      ? el("div", { class: "row" }, av, el("span", { class: "name" }, label), pill(chip.text, chip.cls))
      : el("button", { class: "row", onclick: () => showCall(c) }, av, el("span", { class: "name" }, label), pill(chip.text, chip.cls));
  };
  const items = [...onCall.map(row), ...finished.map(row)];
  if (queued.length) items.push(el("div", { class: "row" }, el("span", { class: "avatar sm grey", "aria-hidden": "true" }, String(queued.length)), el("span", { class: "name" },
    queued.length === 1 ? queued[0].farmer_name : `${queued.length} farmers`), pill("Queued")));
  $("calls").replaceChildren(...(items.length ? items
    : [el("p", { class: "muted" }, "No calls yet. Start the campaign on the Setup page.")]));
}

function showCall(c) {
  $("call-dialog-title").textContent = `${c.farmer_name} · ${KIND_WORD[c.kind]}`;
  const chip = callChip(c);
  const body = [el("p", { style: "margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap" }, pill(chip.text, chip.cls), c.summary || "")];
  if (c.consent && c.transcript && c.transcript.length) {
    body.push(el("div", { class: "transcript" }, c.transcript.map((l) => el("div", { class: `bubble ${l.who}` },
      el("span", { class: "who" }, l.who === "agent" ? "Agent" : c.farmer_name), el("span", {}, l.text),
      l.translation ? el("span", { class: "tr" }, l.translation) : null))));
  } else {
    body.push(el("p", { class: "muted", style: "margin:12px 0" }, c.status === "dropped"
      ? "The call dropped before it finished. Answers saved during the call are kept."
      : "No transcript: the farmer did not consent to one being kept."));
  }
  $("call-dialog-body").replaceChildren(...body);
  $("call-dialog").showModal();
}

function renderLog() {
  const calls = [...state.calls].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  $("log-body").replaceChildren(calls.length ? el("table", {},
    el("thead", {}, el("tr", {}, ["Farmer", "Call", "Status", "Summary", ""].map((h) => el("th", {}, h)))),
    el("tbody", {}, calls.map((c) => {
      const chip = callChip(c);
      return el("tr", {}, el("td", {}, c.farmer_name), el("td", {}, KIND_WORD[c.kind]), el("td", {}, pill(chip.text, chip.cls)),
        el("td", {}, c.summary || el("span", { class: "muted" }, "–")),
        el("td", {}, ["done", "declined", "dropped"].includes(c.status)
          ? el("button", { class: "btn", style: "min-height:36px", onclick: () => { $("log-dialog").close(); showCall(c); } }, "Details") : null));
    }))) : el("p", { class: "muted" }, "No calls yet."));
}

subscribe((s) => { state = s; render(); }, (s) => shell.status(s));
// Keep the on-call timers ticking between updates.
setInterval(() => { if (state && state.calls.some((c) => c.status === "on_call")) renderCalls(); }, 1000);
