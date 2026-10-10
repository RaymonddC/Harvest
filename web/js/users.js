import { act, api, avatar, can, el, getSession, mountShell, pill } from "./data.js";

const $ = (id) => document.getElementById(id);
const shell = mountShell("users");
shell.update({ offers: [] });  // no live data on this page: drop the loading placeholders
const me = getSession();
let data = { users: [], roles: [], capabilities: {} };
let editing = null;

if (!can("users.admin")) {
  document.querySelector("main").replaceChildren(el("div", { class: "banner error", role: "alert" },
    "Only a user with the right to manage users can open this page. Use Switch user to sign in as the Planner."));
} else {
  load();
}

async function load() {
  try {
    data = await api("/api/users", { method: "GET" });
  } catch (err) {
    if (err.status === 401) return act(async () => { throw err; });
    document.querySelector("main").prepend(el("div", { class: "banner error", role: "alert" }, err.message));
    return;
  }
  render();
}

const roleLabel = (id) => data.roles.find((r) => r.id === id)?.label || id;

function render() {
  const active = data.users.filter((u) => u.active).length;
  $("users-count").textContent = `${data.users.length} users, ${active} can sign in`;
  $("user-rows").replaceChildren(...data.users.map((u) => el("tr", {},
    el("td", { style: "padding-left:22px" }, el("div", { class: "who-cell" }, avatar(u.name, "sm"),
      el("div", {}, el("b", {}, u.name), u.id === me.user_id ? el("span", {}, "You") : null))),
    el("td", {}, roleLabel(u.role)),
    el("td", {}, u.active ? pill("Can sign in", "mint") : pill("Turned off")),
    el("td", { class: "r", style: "padding-right:22px;white-space:nowrap" },
      el("button", { class: "btn sm", type: "button", onclick: () => openForm(u) }, "Edit"), " ",
      el("button", { class: "btn sm", type: "button", disabled: u.id === me.user_id, onclick: () => {
        if (confirm(`Delete ${u.name}? They can no longer sign in. Offers they approved keep their name.`)) {
          act(() => api(`/api/users/${u.id}`, { method: "DELETE" }), `${u.name} deleted.`).then(load);
        }
      } }, "Delete")))));

  const caps = Object.entries(data.capabilities);
  $("role-head").replaceChildren(el("tr", {}, el("th", { style: "padding-left:22px" }, "Right"),
    ...data.roles.map((r) => el("th", { class: "r", title: r.description }, r.label))));
  $("role-rows").replaceChildren(...caps.map(([key, label]) => el("tr", {},
    el("td", { style: "padding-left:22px" }, label),
    ...data.roles.map((r) => el("td", { class: "r" }, r.capabilities.includes(key) ? "Yes" : "–")))));
}

function openForm(user) {
  editing = user || null;
  const f = $("user-form");
  f.reset();
  f.elements.role.replaceChildren(...data.roles.map((r) => new Option(r.label, r.id)));
  f.elements.name.value = user ? user.name : "";
  f.elements.role.value = user ? user.role : "viewer";
  f.elements.active.checked = user ? user.active : true;
  $("active-row").hidden = !user;
  $("user-title").textContent = user ? `Edit ${user.name}` : "Add a user";
  $("user-send").textContent = user ? "Save changes" : "Add user";
  showRoleHelp();
  $("user-dialog").showModal();
}
function showRoleHelp() {
  $("role-help").textContent = data.roles.find((r) => r.id === $("user-form").elements.role.value)?.description || "";
}

$("add-open").onclick = () => openForm(null);
$("user-cancel").onclick = () => $("user-dialog").close();
$("user-form").elements.role.onchange = showRoleHelp;
$("user-form").onsubmit = (e) => {
  e.preventDefault();
  const f = $("user-form").elements;
  const body = { name: f.name.value, role: f.role.value, active: editing ? f.active.checked : true };
  const edit = editing;
  act(() => (edit ? api(`/api/users/${edit.id}`, { method: "PUT", body }) : api("/api/users", { body })),
    () => { $("user-dialog").close(); return edit ? "User saved." : "User added."; }).then(load);
};
