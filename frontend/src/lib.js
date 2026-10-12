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
