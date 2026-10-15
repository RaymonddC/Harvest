// The data layer (API, demo sign-in, live stream, formatting) is shared with the vanilla call
// client, so both stay in step: it lives in web/js/data.js and is used here as it is.
export {
  api, apiUrl, callChip, cfg, clearSession, cropLabel, fmtKg, fmtPrice, fmtT, getSession, ICON_PATHS,
  initials, KIND_WORD, maskPhone, plainPrice, roleLabel, can, signIn, subscribe,
} from "../../web/js/data.js";

// Planner pages: route, sidebar label (the key is also the icon name). "need" is the capability a
// page requires before it shows in the sidebar.
export const PAGES = [
  { key: "setup", to: "/setup", label: "Setup" },
  { key: "forecast", to: "/", label: "Live forecast" },
  { key: "approvals", to: "/approvals", label: "Approvals" },
  { key: "users", to: "/users", label: "Users", need: "users.admin" },
];

// The old one-file-per-page URLs (the call client and bookmarks still use them).
export const OLD_URLS = { "index.html": "/", "setup.html": "/setup", "approvals.html": "/approvals", "users.html": "/users", "login.html": "/login" };

// Gap-fill calls ring the farmers' real phones (one at a time) when the backend has phone calls on,
// otherwise they wait in the browser call client as demo calls.
export const gapFillBody = (state, crop) => ({ kind: "gap_fill", crop, channel: state?.settings?.phone_calls ? "twilio" : "browser" });
export const gapFillToast = (r) => (r.channel === "twilio"
  ? `${r.queued} gap-fill calls: ringing the farmers' phones one at a time.`
  : `${r.queued} gap-fill calls queued. Answer them in the call client.`);
// While a campaign runs: the call client for demo calls, the live forecast for real phone calls.
export const followCalls = (campaign) => (campaign?.channel === "twilio"
  ? { href: "/", label: "Watch the phone calls", external: false }
  : { href: "/call.html", label: "Open call client", external: true });
