// Data layer shared by every page.
// Reads: Firestore listeners when a Firebase config is present, otherwise server-sent
// events from the backend. Writes always go through the backend API (Firestore rules
// block client writes).

export const cfg = Object.assign({ apiBase: "", firebase: null, millName: "the cooperative", plannerName: "Planner", needsToken: false },
  window.HARVEST_CONFIG || {});

const COLLECTIONS = ["farmers", "calls", "harvests", "forecast", "offers", "limits", "rival_quotes", "campaigns"];

export function apiUrl(path) {
  return (cfg.apiBase || "").replace(/\/$/, "") + path;
}

export function wsUrl(path) {
  if (cfg.apiBase) return cfg.apiBase.replace(/^http/, "ws").replace(/\/$/, "") + path;
  return (location.protocol === "https:" ? "wss://" : "ws://") + location.host + path;
}

function token() {
  try { return localStorage.getItem("plannerToken") || ""; } catch { return ""; }
}
export function setToken(value) {
  try { localStorage.setItem("plannerToken", value); } catch { /* storage blocked */ }
}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

export async function api(path, { method = "POST", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  const t = token();
  if (t) headers["X-Planner-Token"] = t;
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

// Run a planner action; on 401 ask for the token.
export async function act(fn, okMessage) {
  try {
    const result = await fn();
    if (okMessage) toast(typeof okMessage === "function" ? okMessage(result) : okMessage);
    return result;
  } catch (err) {
    if (err.status === 401) { askToken(); return undefined; }
    toast(err.message, true);
    return undefined;
  }
}

function askToken() {
  let d = document.getElementById("token-dialog");
  if (!d) {
    d = el("dialog", { id: "token-dialog", "aria-labelledby": "token-title" },
      el("h2", { id: "token-title" }, "Planner token"),
      el("p", { class: "muted", style: "margin:8px 0 12px" }, "This dashboard asks for the planner token before it changes anything."),
      el("input", { type: "password", id: "token-input", "aria-label": "Planner token" }),
      el("div", { style: "margin-top:12px;display:flex;gap:8px" },
        el("button", { class: "btn solid", onclick: () => { setToken(document.getElementById("token-input").value.trim()); d.close(); toast("Token saved. Try again."); } }, "Save"),
        el("button", { class: "btn", onclick: () => d.close() }, "Cancel")));
    document.body.append(d);
  }
  d.showModal();
}

// Shared header: brand, three pages, workspace and planner. Returns update(state).
export function mountShell(active) {
  const pages = [["setup", "setup.html", "Setup"], ["forecast", "index.html", "Live forecast"], ["approvals", "approvals.html", "Approvals"]];
  const links = {};
  const nav = el("nav", { "aria-label": "Planner pages" }, pages.map(([key, href, label]) => {
    links[key] = el("a", { href, "aria-current": key === active ? "page" : null }, label);
    return links[key];
  }));
  const header = el("header", { class: "site-header" }, el("div", { class: "inner" },
    el("a", { class: "brand", href: "index.html" }, "Harvest-Call"), nav,
    el("span", { class: "who" }, `${cfg.millName} · Planner: ${cfg.plannerName}`)));
  document.body.prepend(header);
  const banner = el("div", { class: "banner", hidden: true, role: "status" });
  document.querySelector("main")?.prepend(banner);
  return {
    update(state) {
      const n = state.offers.filter((o) => ["pending", "escalated"].includes(o.status)).length;
      links.approvals.textContent = n ? `Approvals · ${n} pending` : "Approvals";
    },
    status(s) {
      banner.hidden = s === "live";
      banner.className = "banner" + (s === "error" ? " error" : "");
      banner.textContent = s === "error" ? "Cannot reach the live data. Check the backend URL in config.js, then reload."
        : "Reconnecting to live data…";
    },
  };
}
