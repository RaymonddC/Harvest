import { campaignsOf, farmerCampaign } from "./campaigns.jsx";

/*
 * Farmers as CRM contacts: each farmer in a campaign has a stage (like a sales pipeline) and, when they need a
 * harvest call, the reason. The reason rule is the backend's services.call_reason; keep the two in step.
 *
 *   To call    no current harvest answer (none, unsure, or its date has passed), or marked to call
 *   Calling    a call is waiting or on now
 *   No answer  the last call did not reach them, and they still need one
 *   Answered   a firm, current harvest is on record
 *   Offer      an offer to them waits for the planner
 *   Deal       an approved deal (purchase order)
 *   Delivered  the deal's fruit reached the weighbridge
 */
export const REASONS = {
  no_answer: "No harvest answer yet",
  unsure: "Answer was unsure",
  date_passed: "Harvest date has passed",
  flagged: "Marked to call",
};

export const STAGES = [
  { key: "to_call", label: "To call", hint: "No current harvest answer" },
  { key: "calling", label: "Calling", hint: "Call waiting or on now" },
  { key: "no_reply", label: "No answer", hint: "The last call did not reach them" },
  { key: "answered", label: "Answered", hint: "Firm harvest on record" },
  { key: "offer", label: "Offer", hint: "Waiting for your approval" },
  { key: "deal", label: "Deal", hint: "Approved: purchase order" },
  { key: "delivered", label: "Delivered", hint: "At the weighbridge" },
];

const NOT_REACHED = ["no_answer", "busy", "failed", "canceled", "not_connected", "dropped"];

export function callReason(f, h, cutoff) {
  if (!f || f.type === "supplier" || f.do_not_call) return null;
  if (!h) return "no_answer";
  if (h.ready_date && h.ready_date < cutoff && !h.every_days) return "date_passed";
  if (h.confidence === "unsure") return "unsure";
  if (f.to_call) return "flagged";
  return null;
}

// Everything about the campaign's farmers in one pass: reason, stage, harvest, open call, last call, offers.
export function crmOf(state, cid) {
  if (!state) return { farmers: [], byId: new Map(), counts: {}, reasons: {} };
  const camps = campaignsOf(state);
  const today = new Date().toISOString().slice(0, 10);
  const planStart = state.settings?.plan_start || today;
  const cutoff = today < planStart ? today : planStart;
  const harvests = new Map(state.harvests.map((h) => [h.farmer_id, h]));
  const calls = new Map();
  for (const c of state.calls) (calls.get(c.farmer_id) || calls.set(c.farmer_id, []).get(c.farmer_id)).push(c);
  const offers = new Map();
  for (const o of state.offers) (offers.get(o.farmer_id) || offers.set(o.farmer_id, []).get(o.farmer_id)).push(o);
  const list = state.farmers.filter((f) => f.type !== "supplier" && farmerCampaign(f, camps) === cid).map((f) => {
    const h = harvests.get(f.id) || null;
    const mine = (calls.get(f.id) || []).sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    const open = mine.find((c) => ["queued", "on_call"].includes(c.status));
    const last = mine.find((c) => !["queued", "on_call"].includes(c.status));
    const fo = offers.get(f.id) || [];
    const pending = fo.find((o) => ["pending", "escalated"].includes(o.status));
    const deal = fo.find((o) => o.status === "approved");
    const reason = callReason(f, h, cutoff);
    let stage = "answered";
    if (open) stage = "calling";
    else if (pending) stage = "offer";
    else if (deal) stage = deal.delivered_kg > 0 ? "delivered" : "deal";
    else if (reason && last && (last.kind === "collect" || last.kind === "gap_fill") && NOT_REACHED.includes(last.outcome)) stage = "no_reply";
    else if (reason) stage = "to_call";
    return { farmer: f, harvest: h, reason, stage, open, last, pending, deal };
  });
  const counts = Object.fromEntries(STAGES.map((s) => [s.key, 0]));
  const reasons = Object.fromEntries(Object.keys(REASONS).map((k) => [k, 0]));
  for (const x of list) {
    counts[x.stage] += 1;
    if (x.reason) reasons[x.reason] += 1;
  }
  return { farmers: list, byId: new Map(list.map((x) => [x.farmer.id, x])), counts, reasons };
}

// The farmers who need a harvest call, and the ones the forecast has nothing current from (no answer, or out of date).
export function toCallOf(state, cid) {
  const { farmers } = crmOf(state, cid);
  const toCall = farmers.filter((x) => x.reason);
  const unknown = toCall.filter((x) => x.reason === "no_answer" || x.reason === "date_passed");
  return { toCall: toCall.map((x) => x.farmer), unknown: unknown.map((x) => x.farmer),
    usualKg: unknown.reduce((n, x) => n + (x.farmer.usual_kg_week || 0), 0) };
}
