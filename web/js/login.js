import { ROLE_LABEL, cfg, getSession, signIn } from "./data.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const notice = $("notice");

// Only ever return to one of our own pages.
const next = /^[a-z]+\.html$/.test(params.get("next") || "") ? params.get("next") : "index.html";
const HOME = { planner: next, viewer: next, farmer: "call.html" };

$("planner-desc").textContent = `${cfg.plannerName}, the mill's planner. Starts call campaigns, sets price limits, approves or rejects deals.`;

if (params.get("expired")) {
  notice.textContent = "Your session ended. Pick a role to continue.";
  notice.hidden = false;
}
const current = getSession();
if (current) {
  $("current").textContent = `Currently signed in as ${current.name} (${ROLE_LABEL[current.role]}). Picking a role below switches you.`;
  $("current").hidden = false;
}

const tiles = [...document.querySelectorAll(".role-tile")];
for (const tile of tiles) {
  tile.onclick = async () => {
    const role = tile.dataset.role;
    tiles.forEach((t) => { t.disabled = true; });
    notice.hidden = true;
    try {
      await signIn(role);
      location.assign(HOME[role]);
    } catch (err) {
      notice.textContent = err.status ? err.message : `${err.message || "Cannot reach the server."} Check the backend URL in config.js.`;
      notice.hidden = false;
      tiles.forEach((t) => { t.disabled = false; });
    }
  };
}
