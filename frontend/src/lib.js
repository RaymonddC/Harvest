// The data layer (API, demo sign-in, live stream, formatting) is shared with the vanilla call
// client, so both stay in step: it lives in web/js/data.js and is used here as it is.
export {
  api, apiUrl, callChip, cfg, clearSession, cropLabel, download, fmtKg, fmtPrice, fmtT, getSession, ICON_PATHS,
  initials, KIND_WORD, maskPhone, plainPrice, roleLabel, can, signIn, subscribe,
} from "../../web/js/data.js";
import { api as dataApi } from "../../web/js/data.js";

// Planner pages: route, sidebar label (the key is also the icon name). "need" is the capability a
// page requires before it shows in the sidebar.
// The sidebar follows the planner's flow: prepare, call, watch, decide. Each page says what its step is for
// and which page comes next. Users is admin work, so it lives in the account menu, not here.
export const OVERVIEW = { id: "overview", label: "Overview" };
export const FLOW = [
  { n: 1, id: "prepare", label: "Prepare" },
  { n: 2, id: "call", label: "Call" },
  { n: 3, id: "decide", label: "Decide" },
];
export const PAGES = [
  { key: "overview", to: "/", label: "Overview", tab: "Summary", step: "overview", next: "setup",
    line: "Where everything stands: what we have and lack, what to do next, and every farmer's stage." },
  { key: "forecast", to: "/forecast", label: "Live forecast", tab: "Forecast", step: "overview", next: "approvals",
    line: "Every saved answer updates the weeks. When a week is short, gap-fill calls ask farmers to bring harvest forward." },
  { key: "calendar", to: "/calendar", label: "Calendar", tab: "Calendar", step: "overview", next: "setup",
    line: "The plan by day: calls, harvests, deal deliveries and weighbridge deliveries." },
  { key: "farmers", to: "/farmers", label: "Farmers", step: "prepare", next: "setup",
    line: "Every farmer the mill works with. A campaign only calls the farmers you put in it." },
  { key: "setup", to: "/setup", label: "Campaign", step: "prepare", next: "calls",
    line: "Pick the campaign, check its farmers and the crop's fair price range, then start calling." },
  { key: "agent", to: "/agent", label: "Agent", step: "settings",
    line: "A setting, not a weekly step: how the AI agent sounds on this campaign's calls and what it asks besides the harvest." },
  { key: "calls", to: "/calls", label: "Calls", step: "call", next: "approvals",
    line: "The agent phones each farmer (outbound) and saves the harvest they give. Follow the calls here; in demo mode this page also plays the farmer's phone." },
  { key: "approvals", to: "/approvals", label: "Approvals", step: "decide", next: "overview",
    line: "Nothing is agreed until you approve. The farmer then hears the confirmation and the purchase order is ready." },
];
// Set once and changed rarely: below the flow, under "Settings" (Users is in the account menu).
export const SETTINGS = { id: "settings", label: "Settings" };
export const ADMIN_PAGES = [{ key: "users", to: "/users", label: "Users", need: "users.admin" }];

// The old one-file-per-page URLs (the call client and bookmarks still use them).
export const OLD_URLS = { "index.html": "/forecast", "setup.html": "/setup", "approvals.html": "/approvals", "users.html": "/users", "login.html": "/login" };

// Gap-fill calls ring the farmers' real phones (one at a time) when the backend has phone calls on,
// otherwise they wait in the browser call client as demo calls.
export const gapFillBody = (state) => ({ kind: "gap_fill", channel: state?.settings?.phone_calls ? "twilio" : "browser" });
// The real-call allowlist: the server's numbers (REAL_CALL_ALLOWLIST) plus the ones added in the dashboard.
// Same comparison as the backend: "+" and the digits.
export const e164 = (phone) => `+${String(phone || "").replace(/\D/g, "")}`;
// Reads the dashboard repeats (traceability, track record, ...) are kept for this visit, so a page shows the last
// answer at once and refreshes it in place instead of popping a card in later and pushing the page down.
const GET_CACHE = new Map();
export const peekGet = (url) => GET_CACHE.get(url);
export const cachedGet = (url) => dataApi(url, { method: "GET" }).then((r) => { GET_CACHE.set(url, r); return r; });

// Real calls reach farmers with Agent calls on, and the numbers in REAL_CALL_ALLOWLIST on the server.
export const numberAllowed = (state, phone) => {
  const s = state?.settings || {};
  if (s.allow_any_number) return true;
  const n = e164(phone);
  return (s.server_allowlist || []).includes(n) || (state?.farmers || []).some((f) => f.agent_calls && e164(f.phone) === n);
};
// Purchase orders (PDF): an approved deal, or what a finished call agreed (a draft when only a harvest was saved).
export const offerPoUrl = (id) => `/api/offers/${encodeURIComponent(id)}/purchase-order.pdf`;
export const callPoUrl = (id) => `/api/calls/${encodeURIComponent(id)}/purchase-order.pdf`;
// Start or stop one campaign's calls.
export const startUrl = (cid) => `/api/campaigns/${encodeURIComponent(cid)}/start`;
export const stopUrl = (cid) => `/api/campaigns/${encodeURIComponent(cid)}/stop`;
export const gapFillToast = (r) => (r.channel === "twilio"
  ? `${r.queued} gap-fill calls: ringing the farmers' phones one at a time.`
  : `${r.queued} gap-fill demo calls ready on the Calls page.`);
// While a campaign runs: the call client for demo calls, the live forecast for real phone calls.
export const followCalls = (campaign) => (campaign?.channel === "twilio"
  ? { href: "/forecast", label: "Watch the phone calls", external: false }
  : { href: "/calls", label: "Open the demo phone", external: false });
