import { campaignFor, inCampaign } from "./campaigns.jsx";
import { toCallOf } from "./crm.js";
import { fmtT } from "./lib.js";
import { dueFollowUps } from "./components/setup/Relationship.jsx";

// What is lacking in a campaign and what to do about it, most urgent first: each item is the problem ("what"), the
// next action ("next") and where it is done ("to"). The sidebar shows the first few; the Overview shows them all.
export function todoItems(state, cid) {
  if (!state) return [];
  const campaign = campaignFor(state, cid);
  const running = campaign.status === "running";
  const rows = inCampaign(state, state.forecast, cid).sort((a, b) => a.week - b.week);
  const gap = rows.find((r) => r.is_gap);
  const over = rows.find((r) => r.is_surplus);
  const waiting = inCampaign(state, state.offers, cid).filter((o) => ["pending", "escalated"].includes(o.status)).length;
  const { toCall, byHand, unknown, usualKg } = toCallOf(state, cid);
  const confirming = inCampaign(state, state.calls, cid).filter((c) => c.kind === "confirm" && ["queued", "on_call"].includes(c.status)).length;
  const items = [];
  if (running) {
    items.push({ key: "running", verb: "Follow", to: campaign.channel === "twilio" ? "/forecast" : "/calls", tone: "on",
      what: campaign.kind === "gap_fill" ? "Gap-fill calls running" : "Harvest calls running",
      next: campaign.channel === "twilio" ? "Watch the answers arrive" : "Answer them on the demo phone" });
  }
  if (waiting) items.push({ key: "approve", verb: "Review", to: "/approvals", tone: "amber", what: `${waiting} offer${waiting > 1 ? "s" : ""} waiting for you`, next: "Approve or reject" });
  if (!running && toCall.length) {
    items.push({ key: "call", verb: "Call them", to: "/setup#farmer-list", tone: "amber", what: `${toCall.length} farmers need a harvest call`,
      next: unknown.length ? `Call them: about ${fmtT(usualKg)} t a week is still unknown` : "Call them: their answers were unsure" });
  }
  const members = new Set(inCampaign(state, state.farmers, cid).map((f) => f.id));
  const due = dueFollowUps(state, members);
  if (due.length) {
    items.push({ key: "followup", verb: "See them", to: "/setup#farmer-list", tone: "amber",
      what: `${due.length} follow-up${due.length > 1 ? "s" : ""} due`, next: due.slice(0, 2).map((n) => n.farmer_name).join(", ") + (due.length > 2 ? " and others" : "") });
  }
  if (byHand.length) {
    items.push({ key: "byhand", verb: "See them", to: "/setup#farmer-list", tone: "amber",
      what: `${byHand.length} farmer${byHand.length > 1 ? "s" : ""} to call yourself`,
      next: "Agent calls is off for them: call them and enter their harvest on their card" });
  }
  if (gap) {
    const forward = (gap.shortlist || []).length;
    items.push({ key: "gap", verb: "Fill it", to: "/forecast", tone: "amber", what: `Week ${gap.week} is ${fmtT(gap.gap_kg)} t short${usualKg ? `, ${fmtT(Math.max(gap.gap_kg - usualKg, 0))} t if the ${unknown.length} farmers who have not answered bring their usual` : ""}`,
      next: running && campaign.kind === "gap_fill" ? "Gap-fill calls are on it" : forward ? `Start gap-fill calls: ${forward} farmers can help` : "Add a rival quote or farmers who can harvest earlier" });
  }
  if (over) items.push({ key: "over", verb: "Move some", to: "/forecast", tone: "red", what: `Week ${over.week} is ${fmtT(over.surplus_kg)} t over capacity`, next: "Ask some farmers to deliver a week later" });
  if (confirming) items.push({ key: "confirm", verb: "See calls", to: "/calls", tone: "on", what: `${confirming} confirmation call${confirming > 1 ? "s" : ""} to make`, next: "The agent tells farmers their approved deal" });
  if (!inCampaign(state, state.farmers, cid).length) items.push({ key: "farmers", verb: "Add farmers", to: "/setup", tone: "amber", what: "No farmers in this campaign", next: "Add farmers from the database" });
  return items;
}

export const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const nextAutoText = (campaign) => (campaign.weekly?.enabled
  ? `next automatic calls ${(campaign.weekly.days || [0]).map((d) => DAY_SHORT[d]).join(", ")} at ${campaign.weekly.time || "06:00"}` : "");
