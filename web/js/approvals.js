import { act, api, avatar, el, fmtT, mountShell, pill, plainPrice, subscribe } from "./data.js";

const $ = (id) => document.getElementById(id);
const shell = mountShell("approvals");
let state = null;

// The week this screen is about: where most offers deliver, else the first gap week.
function focusWeek() {
  const counts = {};
  for (const o of state.offers) if (o.deliver_week) counts[o.deliver_week] = (counts[o.deliver_week] || 0) + 1;
  const busiest = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  if (busiest) return Number(busiest[0]);
  const gap = [...state.forecast].sort((a, b) => a.week - b.week).find((r) => r.is_gap);
  return gap ? gap.week : null;
}

function detail(o) {
  const n = o.negotiation || {};
  const cur = o.currency || "IDR";
  const parts = [];
  if (o.village && o.kind !== "supplier") parts.push(o.village);
  if (n.rival_quote) parts.push("Logged rival quote, used after farmers");
  else if (o.status === "escalated" || n.escalated) parts.push(`Asked ${plainPrice(o.requested_price, cur)}, above the ceiling`);
  else if (n.counter && n.first_offer && n.counter > n.first_offer) parts.push(`Countered from ${plainPrice(n.first_offer, cur)}, accepted inside the ceiling`);
  else if (n.counter && n.first_offer && n.counter < n.first_offer) parts.push("Asked less than our offer; paid at least the floor");
  else if (n.rung > 0) parts.push(`Accepted step ${n.rung + 1} of the offer ladder`);
  else parts.push("Accepted the first offer");
  if (o.from_week) parts.push(`moves delivery from week ${o.from_week}`);
  return parts.join(" · ");
}

function render() {
  shell.update(state);
  const week = focusWeek();
  const row = state.forecast.find((r) => r.week === week);
  $("title").textContent = week ? `Approve gap-fill deals · week ${week}` : "Approve gap-fill deals";

  // Gap meter: the gap before any approval, and how much approved offers have closed.
  if (row) {
    const closed = row.approved_in_kg || 0;
    const original = Math.max(row.target_kg - (row.expected_kg - closed), 0);
    const remaining = Math.max(original - closed, 0);
    const share = original ? Math.min(closed / original, 1) : 1;
    $("meter-card").hidden = false;
    $("meter-text").replaceChildren(el("strong", {}, `${(closed / 1000).toFixed(1)} t`), ` of ${(original / 1000).toFixed(1)} t closed · `,
      el("strong", {}, `${(remaining / 1000).toFixed(1)} t`), " still short");
    $("meter-fill").style.width = `${share * 100}%`;
    $("meter").setAttribute("aria-valuenow", String(Math.round(share * 100)));
    const awaiting = state.calls.filter((c) => c.kind === "confirm" && c.status === "queued").length;
    $("meter-done").replaceChildren(...(remaining < 50 && original > 0 ? [el("div", { class: "meter-done" },
      el("span", {}, `Week ${week} gap closed. ${awaiting ? "Confirmation calls are ready to go out." : "Confirmations are done."}`),
      el("a", { class: "btn leaf", href: "call.html", target: "_blank", rel: "noopener" }, "Hear a confirmation call"))]
      : !row.is_gap && closed > 0 ? [el("p", { class: "sub" }, `Week ${week} is no longer flagged as a gap. ${fmtT(remaining)} t is still below the target.`)] : []));
  } else {
    $("meter-card").hidden = true;
  }

  const order = { pending: 0, escalated: 1, approved: 2, rejected: 3 };
  const offers = [...state.offers].sort((a, b) => order[a.status] - order[b.status] || (a.created_at || "").localeCompare(b.created_at || ""));
  const limits = Object.fromEntries(state.limits.map((l) => [l.id, l]));

  const quotes = state.rival_quotes.filter((q) => !state.offers.some((o) => o.source === `rival_quote:${q.id}` && ["pending", "approved"].includes(o.status)));
  const rows = offers.map((o) => {
    const l = limits[o.crop];
    // An escalated offer is approved at the farmer's requested price, so that is what must fit.
    const price = o.status === "escalated" && o.requested_price != null ? o.requested_price : o.price_per_kg;
    const inLimits = l && price >= l.floor_price && price <= l.ceiling_price;
    const cur = o.currency || "IDR";
    let acts;
    if (o.status === "pending" || o.status === "escalated") {
      acts = [
        o.status === "pending" ? pill("Pending", "amber") : pill("Needs planner", "danger"),
        el("button", { class: "btn", onclick: () => act(() => api(`/api/offers/${o.id}/reject`), `Rejected. ${o.farmer_name} will not be confirmed.`) }, "Reject"),
        el("button", { class: "btn leaf", disabled: !inLimits, title: inLimits ? null : "Outside the current floor and ceiling",
          onclick: () => act(() => api(`/api/offers/${o.id}/approve`), `Approved. A confirmation call to ${o.farmer_name} is queued.`) }, "Approve"),
      ];
    } else {
      const confirmed = o.status === "approved" && o.confirmed_by_voice;
      acts = [
        pill(confirmed ? "Approved · confirmed by voice" : o.status === "approved" ? "Approved" : "Rejected", o.status === "approved" ? "mint" : ""),
        confirmed ? null : el("button", { class: "btn ghost", onclick: () => act(() => api(`/api/offers/${o.id}/undo`), "Back to pending.") }, "Undo"),
      ];
    }
    return el("div", { class: `offer is-${o.status}` },
      el("div", { class: "who" }, avatar(o.farmer_name, o.kind === "supplier" ? "ink" : ""), el("div", {}, el("b", {}, o.farmer_name), el("span", {}, detail(o)))),
      el("div", { class: "fig" }, el("span", {}, "Volume"), el("b", { class: "num" }, `${(o.kg / 1000).toFixed(1)} t`)),
      el("div", { class: "fig" }, el("span", {}, `Price, ${cur}/kg`), el("b", { class: "num" }, plainPrice(o.price_per_kg, cur))),
      el("div", { class: "acts" }, acts),
      o.status === "escalated" && !inLimits ? el("p", { class: "warn" }, `Above the ceiling of ${plainPrice(l ? l.ceiling_price : 0, cur)}. Raise the ceiling on the Setup page to approve, or reject.`) : null);
  });
  for (const q of quotes) {
    rows.push(el("div", { class: "offer" },
      el("div", { class: "who" }, avatar(q.supplier_name, "ink"), el("div", {}, el("b", {}, q.supplier_name), el("span", {}, `Logged quote for week ${q.deliver_week}, not used yet`))),
      el("div", { class: "fig" }, el("span", {}, "Volume"), el("b", { class: "num" }, `${(q.kg / 1000).toFixed(1)} t`)),
      el("div", { class: "fig" }, el("span", {}, `Price, ${q.currency || "IDR"}/kg`), el("b", { class: "num" }, plainPrice(q.price_per_kg, q.currency || "IDR"))),
      el("div", { class: "acts" }, el("button", { class: "btn", onclick: () => act(() => api(`/api/rival-quotes/${q.id}/offer`), "Rival quote added as a pending offer.") }, "Add as offer"))));
  }
  $("offers").replaceChildren(...(rows.length ? rows : [el("div", { class: "empty" },
    el("p", {}, "No offers yet. Offers appear here as the agent agrees them on gap-fill calls."),
    el("a", { class: "btn", href: "index.html" }, "Go to the live forecast"))]));

  const l = state.limits[0];
  const anyOut = offers.some((o) => o.status === "escalated");
  $("offers-foot").textContent = l
    ? `${anyOut ? "Offers marked Needs planner asked for more than the ceiling. All others are" : "All offers are"} inside the floor (${plainPrice(l.floor_price, l.currency)}) and ceiling (${plainPrice(l.ceiling_price, l.currency)}). Synthetic data.`
    : "";
}

subscribe((s) => { state = s; render(); }, (s) => shell.status(s));
