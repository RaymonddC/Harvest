// Data layer shared by every page.
// Reads: Firestore listeners when a Firebase config is present, otherwise server-sent
// events from the backend. Writes always go through the backend API (Firestore rules
// block client writes).

export const cfg = Object.assign({ apiBase: "", firebase: null, millName: "the cooperative", plannerName: "Planner" },
  window.HARVEST_CONFIG || {});

const COLLECTIONS = ["farmers", "calls", "harvests", "forecast", "offers", "limits", "rival_quotes", "campaigns"];

export function apiUrl(path) {
  return (cfg.apiBase || "").replace(/\/$/, "") + path;
}

export function wsUrl(path) {
  if (cfg.apiBase) return cfg.apiBase.replace(/^http/, "ws").replace(/\/$/, "") + path;
  return (location.protocol === "https:" ? "wss://" : "ws://") + location.host + path;
}

// ---------- demo sign-in: the browser keeps the role token the backend handed out ----------

const SESSION_KEY = "harvestSession";
export const ROLE_LABEL = { planner: "Planner", viewer: "Viewer", farmer: "Farmer" };

export function getSession() {
  try {
    const s = JSON.parse(localStorage.getItem(SESSION_KEY) || "null");
    if (s && s.token && s.exp * 1000 > Date.now()) return s;
  } catch { /* storage blocked or corrupt: treated as signed out */ }
  return null;
}
export function clearSession() {
  try { localStorage.removeItem(SESSION_KEY); } catch { /* storage blocked */ }
}
export async function signIn(role) {
  const session = await api("/api/auth/login", { body: { role }, auth: false });
  try { localStorage.setItem(SESSION_KEY, JSON.stringify(session)); } catch { /* checked below */ }
  if (!getSession()) throw new Error("This browser blocks storage, so the sign-in cannot be kept. Allow site data and try again.");
  return session;
}
function toLogin(expired) {
  const page = location.pathname.split("/").pop() || "index.html";
  location.replace(`login.html?next=${encodeURIComponent(page)}${expired ? "&expired=1" : ""}`);
}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

export async function api(path, { method = "POST", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  const session = auth ? getSession() : null;
  if (session) headers.Authorization = `Bearer ${session.token}`;
  const res = await fetch(apiUrl(path), { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    let msg = data && data.detail ? data.detail : `Request failed (${res.status}).`;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    throw new ApiError(msg, res.status);
  }
  return data;
}

// subscribe(onState, onStatus) -> unsubscribe
export function subscribe(onState, onStatus = () => {}) {
  return cfg.firebase ? firestoreSource(onState, onStatus) : sseSource(onState, onStatus);
}

function sseSource(onState, onStatus) {
  const es = new EventSource(apiUrl("/api/stream"));
  es.onopen = () => onStatus("live");
  es.onmessage = (e) => { onState(JSON.parse(e.data)); onStatus("live"); };
  es.onerror = () => onStatus("reconnecting");
  return () => es.close();
}

function firestoreSource(onState, onStatus) {
  const unsubs = [];
  const state = Object.fromEntries(COLLECTIONS.map((c) => [c, []]));
  let stopped = false;
  (async () => {
    try {
      // Settings (plan start, target, names) come from the backend once.
      Object.assign(state, await api("/api/state", { method: "GET" }));
      onState({ ...state });
      const v = "11.0.2";
      const { initializeApp } = await import(`https://www.gstatic.com/firebasejs/${v}/firebase-app.js`);
      const { getFirestore, collection, onSnapshot } = await import(`https://www.gstatic.com/firebasejs/${v}/firebase-firestore.js`);
      if (stopped) return;
      const db = getFirestore(initializeApp(cfg.firebase));
      for (const name of COLLECTIONS) {
        unsubs.push(onSnapshot(collection(db, name), (snap) => {
          state[name] = snap.docs.map((d) => ({ ...d.data(), id: d.id }));
          onState({ ...state });
          onStatus("live");
        }, () => onStatus("reconnecting")));
      }
    } catch (err) {
      console.error(err);
      onStatus("error");
    }
  })();
  return () => { stopped = true; unsubs.forEach((u) => u()); };
}

// ---------- formatting ----------

// Tonnes with one decimal, dropping a trailing ".0" (61, 22.8).
export const fmtT = (kg) => {
  const r = Math.round(kg / 100) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
};
export const fmtKg = (kg) => Math.round(kg).toLocaleString("en-US");
export const fmtNum = (n) => Number(n).toLocaleString("en-US", { maximumFractionDigits: 2 });
export function fmtPrice(p, cur = "IDR", { unit = true } = {}) {
  if (p === null || p === undefined) return "–";
  const n = cur === "IDR" ? Math.round(p).toLocaleString("en-US") : Number(p).toFixed(2);
  const prefix = cur === "IDR" ? "Rp " : "";
  const suffix = cur === "IDR" ? "" : ` ${cur}`;
  return `${prefix}${n}${suffix}${unit ? "/kg" : ""}`;
}
export const plainPrice = (p, cur = "IDR") => (cur === "IDR" ? Math.round(p).toLocaleString("en-US") : Number(p).toFixed(2));
export const CROP_LABEL = { palm: "Palm FFB", rubber: "Rubber", coffee: "Coffee" };
export const cropLabel = (c) => CROP_LABEL[c] || (c ? c[0].toUpperCase() + c.slice(1) : "");
export function maskPhone(phone = "") {
  const parts = phone.split(" ");
  return parts.length >= 3 ? [...parts.slice(0, 2), "••••", parts[parts.length - 1]].join(" ") : phone;
}
export const KIND_WORD = { collect: "Harvest call", gap_fill: "Gap-fill call", confirm: "Confirmation call" };
export const STATUS_WORD = {
  queued: "Queued", on_call: "On call", done: "Done", dropped: "Dropped", declined: "Declined",
  pending: "Pending", approved: "Approved", rejected: "Rejected", escalated: "Needs planner",
};

export function elapsed(iso) {
  if (!iso) return "00:00";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

// Call status in words, never colour alone.
export function callChip(c) {
  if (c.status === "on_call") return { cls: "leaf", text: `On call · ${elapsed(c.started_at)}` };
  if (c.status === "done") return { cls: "mint", text: c.harvest_confidence ? `Done · ${c.harvest_confidence}` : "Done" };
  if (c.status === "dropped") return { cls: "", text: c.retry_queued ? "Dropped · retry queued" : "Dropped" };
  if (c.status === "declined") return { cls: "", text: "Declined" };
  return { cls: "", text: "Queued" };
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.setAttribute("style", v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export const pill = (text, cls = "") => el("span", { class: `pill ${cls}`.trim() }, text);

let toastTimer;
export function toast(message, isError = false) {
  let t = document.querySelector(".toast");
  if (!t) { t = el("div", { class: "toast", role: "status", "aria-live": "polite" }); document.body.append(t); }
  t.className = "toast" + (isError ? " error" : "");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, isError ? 6000 : 3200);
}

// Run a planner action. Viewers are told why nothing happens; an expired session goes back to sign-in.
export async function act(fn, okMessage) {
  const session = getSession();
  if (session && session.role !== "planner") {
    toast("You are signed in as a viewer. Switch to the Planner role to change anything.", true);
    return undefined;
  }
  try {
    const result = await fn();
    if (okMessage) toast(typeof okMessage === "function" ? okMessage(result) : okMessage);
    return result;
  } catch (err) {
    if (err.status === 401) { clearSession(); toLogin(true); return undefined; }
    toast(err.message, true);
    return undefined;
  }
}

// Two-letter initials for avatar chips: "Pak Rahmat" -> "PR", "Rival supplier" -> "RS".
export function initials(name = "") {
  const words = name.replace(/[^\p{L}\s]/gu, " ").trim().split(/\s+/).filter(Boolean);
  return ((words[0] || "?")[0] + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
}
export const avatar = (name, cls = "") => el("span", { class: `avatar ${cls}`.trim(), "aria-hidden": "true" }, initials(name));

// Inline stroke icons, so the pages need no icon font.
const ICON_PATHS = {
  leaf: '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z"/><path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12"/>',
  setup: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
  forecast: '<path d="M3 3v18h18"/><path d="M7 16v-5"/><path d="M12 16V8"/><path d="M17 16v-9"/>',
  approvals: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>',
  spark: '<path d="M12 3l1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2z"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
};
export function icon(name, size = 18) {
  const span = el("span", { class: "icon", "aria-hidden": "true", style: "display:inline-grid;place-items:center" });
  span.innerHTML = `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name] || ""}</svg>`;
  return span;
}

// Shared frame: sidebar (brand, workspace, pages, planner) and a top bar that takes the
// page's .page-head. Returns update(state) and status(s).
export function mountShell(active) {
  const session = getSession();
  if (!session) toLogin(false);
  const pages = [["setup", "setup.html", "Setup"], ["forecast", "index.html", "Live forecast"], ["approvals", "approvals.html", "Approvals"]];
  const links = {};
  const count = el("span", { class: "count", hidden: true });
  const nav = el("nav", { "aria-label": "Planner pages" }, pages.map(([key, href, label]) => {
    links[key] = el("a", { href, "aria-current": key === active ? "page" : null }, icon(key), el("span", { class: "label" }, label),
      key === "approvals" ? count : null);
    return links[key];
  }));
  const side = el("aside", { class: "side" },
    el("a", { class: "brand", href: "index.html" }, el("span", { class: "mark" }, icon("leaf", 18)), "Harvest-Call"),
    el("div", { class: "workspace-card" }, el("span", {}, "Workspace"), el("b", {}, cfg.millName)),
    nav,
    el("div", { class: "spacer" }),
    el("div", { class: "planner" }, avatar(session ? session.name : "?", "ink"),
      el("div", {}, el("b", {}, session ? session.name : "Signed out"),
        el("span", {}, session ? `${ROLE_LABEL[session.role]} · ` : ""), el("a", { href: "login.html" }, "Switch role"))));

  const main = document.querySelector("main");
  const head = main?.querySelector(".page-head");
  const workspace = el("div", { class: "workspace" });
  if (head) workspace.append(el("div", { class: "topbar" }, head));
  document.body.classList.add("app");
  document.body.prepend(side, workspace);
  if (main) workspace.append(main);

  const banner = el("div", { class: "banner", hidden: true, role: "status" });
  main?.prepend(banner);
  if (session && session.role !== "planner") {
    main?.prepend(el("div", { class: "banner", role: "note" },
      "View only. You can watch the forecast, offers and calls, but anything that changes data is blocked. Use Switch role to sign in as the Planner."));
  }
  return {
    update(state) {
      const n = state.offers.filter((o) => ["pending", "escalated"].includes(o.status)).length;
      count.hidden = !n;
      count.textContent = String(n);
      links.approvals.setAttribute("aria-label", n ? `Approvals, ${n} waiting` : "Approvals");
    },
    status(s) {
      banner.hidden = s === "live";
      banner.className = "banner" + (s === "error" ? " error" : "");
      banner.textContent = s === "error" ? "Cannot reach the live data. Check the backend URL in config.js, then reload."
        : "Reconnecting to live data…";
    },
  };
}
