import { api, getSession, icon, roleLabel, signIn } from "./data.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const notice = $("notice");

// Only ever return to one of our own pages.
const next = /^[a-z]+\.html$/.test(params.get("next") || "") ? params.get("next") : "index.html";
const ROLE_ICON = { planner: "forecast", coordinator: "setup", viewer: "eye", farmer: "phone" };

document.querySelectorAll("[data-icon]").forEach((n) => n.replaceChildren(icon(n.dataset.icon, n.classList.contains("mark") ? 18 : 20)));

if (params.get("expired")) {
  notice.textContent = "Your session ended. Pick a person to continue.";
  notice.hidden = false;
}
const current = getSession();
if (current) {
  $("current").textContent = `Currently signed in as ${current.name} (${roleLabel(current)}). Picking someone below switches you.`;
  $("current").hidden = false;
}

function tile(person, first) {
  const b = document.createElement("button");
  b.className = `role-tile${first ? " main" : ""}`;
  b.dataset.user = person.id;
  const mk = (cls, text) => { const s = document.createElement("span"); s.className = cls; s.textContent = text; return s; };
  const ic = document.createElement("span");
  ic.className = "role-icon";
  ic.append(icon(ROLE_ICON[person.role] || "users", 20));
  b.append(ic, mk("role-name", person.name), mk("role-desc", `${person.role_label}. ${person.description || ""}`.trim()),
    mk("role-go", person.role === "farmer" ? "Open the call client" : "Open the live forecast"));
  return b;
}

(async () => {
  let people;
  try {
    people = (await api("/api/auth/people", { method: "GET", auth: false })).people;
  } catch (err) {
    notice.textContent = `${err.message || "Cannot reach the server."} Check the backend URL in config.js.`;
    notice.hidden = false;
    return;
  }
  const tiles = people.map((p, i) => tile(p, i === 0));
  $("people").replaceChildren(...tiles);
  for (const t of tiles) {
    t.onclick = async () => {
      tiles.forEach((x) => { x.disabled = true; });
      notice.hidden = true;
      const person = people.find((p) => p.id === t.dataset.user);
      try {
        await signIn(person.id);
        location.assign(person.role === "farmer" ? "call.html" : next);
      } catch (err) {
        notice.textContent = err.status ? err.message : `${err.message || "Cannot reach the server."} Check the backend URL in config.js.`;
        notice.hidden = false;
        tiles.forEach((x) => { x.disabled = false; });
      }
    };
  }
})();
