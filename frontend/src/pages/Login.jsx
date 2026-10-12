import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, getSession, OLD_URLS, roleLabel, signIn } from "../lib.js";
import { Icon, Spinner } from "../ui.jsx";

const ROLE_ICON = { planner: "forecast", coordinator: "setup", viewer: "eye", farmer: "phone" };

// Only ever return to one of our own pages: a route ("/setup") or an old file name ("setup.html").
function returnTo(next) {
  if (OLD_URLS[next]) return OLD_URLS[next];
  return ["/", "/setup", "/approvals", "/users"].includes(next) ? next : "/";
}

// Demo sign-in: pick a person (no password). Each person has one role, and the role's rights
// decide what they can do; the server checks every action again.
export default function Login() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [people, setPeople] = useState(null);
  const [busy, setBusy] = useState(null); // the person being signed in
  const [notice, setNotice] = useState(params.get("expired") ? "Your session ended. Pick a person to continue." : "");
  const current = getSession();
  useEffect(() => {
    document.body.className = "login-page";
    document.title = "Sign in · Harvest-Call";
    api("/api/auth/people", { method: "GET", auth: false })
      .then((r) => setPeople(r.people))
      .catch((err) => setNotice(`${err.message || "Cannot reach the server."} Check the backend URL in config.js.`));
  }, []);

  const pick = async (person) => {
    setBusy(person.id);
    setNotice("");
    try {
      await signIn(person.id);
      // The call client is a separate (vanilla) page; everyone else stays in the app.
      if (person.role === "farmer") location.assign("/call.html");
      else navigate(returnTo(params.get("next") || "/"), { replace: true });
    } catch (err) {
      setNotice(err.status ? err.message : `${err.message || "Cannot reach the server."} Check the backend URL in config.js.`);
      setBusy(null);
    }
  };

  return (
    <main className="login">
      <div className="login-head">
        <div className="brand"><span className="mark"><Icon name="leaf" /></span>Harvest-Call</div>
        <h1>Who is signing in?</h1>
        <p className="muted">Demo mode: there is no password, just pick a person. What each person can do depends on their role. All data is synthetic.</p>
      </div>
      {notice && <p className="banner error" role="alert">{notice}</p>}
      <div className="roles" role="group" aria-label="People">
        {(people || []).map((p, i) => (
          <button key={p.id} className={`role-tile ${i === 0 ? "main" : ""}`} disabled={!!busy} aria-busy={busy === p.id || undefined} onClick={() => pick(p)}>
            <span className="role-icon"><Icon name={ROLE_ICON[p.role] || "users"} size={20} /></span>
            <span className="role-name">{p.name}</span>
            <span className="role-desc">{`${p.role_label}. ${p.description || ""}`.trim()}</span>
            <span className="role-go">{busy === p.id ? <><Spinner />Signing in…</> : p.role === "farmer" ? "Open the call client" : "Open the live forecast"}</span>
          </button>
        ))}
      </div>
      {current && <p className="small muted">Currently signed in as {current.name} ({roleLabel(current)}). Picking someone below switches you.</p>}
    </main>
  );
}
