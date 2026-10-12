import { useCallback, useEffect, useState } from "react";
import { api, can, getSession } from "../lib.js";
import Shell from "../Shell.jsx";
import { useAct } from "../toast.jsx";
import { ActButton, Avatar, Dialog, DialogClose, Pill, SubmitButton } from "../ui.jsx";

// Add a user (user = {}) or edit one (user = the record); null keeps it closed.
function UserForm({ user, roles, onClose, onSaved }) {
  const act = useAct();
  const editing = !!user?.id;
  const [f, setF] = useState({ name: "", role: "viewer", active: true });
  useEffect(() => {
    if (user) setF(editing ? { name: user.name, role: user.role, active: user.active } : { name: "", role: "viewer", active: true });
  }, [user, editing]);
  const help = roles.find((r) => r.id === f.role)?.description || "";
  const [saving, setSaving] = useState(false);
  const save = async (e) => {
    e.preventDefault();
    const body = { name: f.name, role: f.role, active: editing ? f.active : true };
    setSaving(true);
    await act(() => (editing ? api(`/api/users/${user.id}`, { method: "PUT", body }) : api("/api/users", { body })),
      () => { onClose(); return editing ? "User saved." : "User added."; });
    setSaving(false);
    onSaved();
  };
  return (
    <Dialog open={!!user} onClose={onClose} title={editing ? `Edit ${user.name}` : "Add a user"}>
      <form onSubmit={save}>
        <div style={{ display: "grid", gap: 10, margin: "12px 0" }}>
          <label className="field">Name <input type="text" required maxLength={60} autoComplete="off" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label className="field">Role
            <select required value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              {roles.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </label>
          <p className="sub" style={{ margin: 0 }}>{help}</p>
          {editing && (
            <label className="field" style={{ flexDirection: "row", gap: 8, alignItems: "center", fontWeight: 400 }}>
              <input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} /> Can sign in
            </label>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <SubmitButton busy={saving} busyText={editing ? "Saving…" : "Adding…"}>{editing ? "Save changes" : "Add user"}</SubmitButton>
          <DialogClose>Cancel</DialogClose>
        </div>
      </form>
    </Dialog>
  );
}

// Who can sign in, and what each role may do. The rights are fixed in the server's code.
export default function Users() {
  const act = useAct();
  const me = getSession();
  const allowed = can("users.admin");
  const [data, setData] = useState({ users: [], roles: [], capabilities: {} });
  const [error, setError] = useState("");
  const [form, setForm] = useState(null); // {} to add, a user to edit, null when closed
  const load = useCallback(async () => {
    try {
      setData(await api("/api/users", { method: "GET" }));
      setError("");
    } catch (err) {
      if (err.status === 401) act(async () => { throw err; }); // back to sign-in
      else setError(err.message);
    }
  }, [act]);
  useEffect(() => { if (allowed) load(); }, [allowed, load]);

  const roleName = (id) => data.roles.find((r) => r.id === id)?.label || id;
  const remove = async (u) => {
    if (confirm(`Delete ${u.name}? They can no longer sign in. Offers they approved keep their name.`)) {
      await act(() => api(`/api/users/${u.id}`, { method: "DELETE" }), `${u.name} deleted.`);
      await load();
    }
  };
  const head = (
    <div className="page-head">
      <div>
        <h1>Users and roles</h1>
        <p>Who can sign in, and what each role may do. A role is a bundle of rights; every approval is recorded under the user who made it.</p>
      </div>
      {allowed && <button className="btn solid" type="button" onClick={() => setForm({})}>Add user</button>}
    </div>
  );

  if (!allowed) {
    return <Shell title="Users" head={head}>
      <div className="banner error" role="alert">Only a user with the right to manage users can open this page. Use Switch user to sign in as the Planner.</div>
    </Shell>;
  }
  const active = data.users.filter((u) => u.active).length;
  const caps = Object.entries(data.capabilities);
  return (
    <Shell title="Users" head={head}>
      {error && <div className="banner error" role="alert">{error}</div>}
      <section className="card" style={{ padding: 0, gap: 0 }} aria-labelledby="users-title">
        <div className="card-head" style={{ padding: "18px 22px", borderBottom: "1px solid var(--line-2)" }}>
          <div><h2 id="users-title">People</h2><div className="sub">{data.users.length} users, {active} can sign in</div></div>
        </div>
        <div className="table-wrap">
          <table style={{ minWidth: 640 }}>
            <thead><tr><th style={{ paddingLeft: 22 }}>Name</th><th>Role</th><th>Status</th><th style={{ paddingRight: 22 }}><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {data.users.map((u) => (
                <tr key={u.id}>
                  <td style={{ paddingLeft: 22 }}><div className="who-cell"><Avatar name={u.name} cls="sm" /><div><b>{u.name}</b>{u.id === me.user_id && <span>You</span>}</div></div></td>
                  <td>{roleName(u.role)}</td>
                  <td>{u.active ? <Pill cls="mint">Can sign in</Pill> : <Pill>Turned off</Pill>}</td>
                  <td className="r" style={{ paddingRight: 22, whiteSpace: "nowrap" }}>
                    <button className="btn sm" type="button" onClick={() => setForm(u)}>Edit</button>{" "}
                    <ActButton className="btn sm" busy="Deleting…" disabled={u.id === me.user_id} run={() => remove(u)}>Delete</ActButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card" aria-labelledby="roles-title">
        <div className="card-head"><h2 id="roles-title">What each role may do</h2></div>
        <div className="table-wrap">
          <table style={{ minWidth: 640 }}>
            <thead><tr><th style={{ paddingLeft: 22 }}>Right</th>{data.roles.map((r) => <th key={r.id} className="r" title={r.description}>{r.label}</th>)}</tr></thead>
            <tbody>
              {caps.map(([key, label]) => (
                <tr key={key}><td style={{ paddingLeft: 22 }}>{label}</td>
                  {data.roles.map((r) => <td key={r.id} className="r">{r.capabilities.includes(key) ? "Yes" : "–"}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">The rights are fixed in the code, because each one is checked by the server. Changing a user's role changes what they can do straight away.</p>
      </section>

      <UserForm user={form} roles={data.roles} onClose={() => setForm(null)} onSaved={load} />
    </Shell>
  );
}
