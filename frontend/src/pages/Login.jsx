import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { cfg, getSession, OLD_URLS, ROLE_LABEL, signIn } from "../lib.js";
import { Icon } from "../ui.jsx";

const ROLES = [
  { role: "planner", icon: "forecast", name: "Planner", go: "Open the live forecast",
    desc: `${cfg.plannerName}, the mill's planner. Starts call campaigns, sets price limits, approves or rejects deals.` },
  { role: "viewer", icon: "eye", name: "Viewer", go: "Open the live forecast",
    desc: "A guest. Watch the forecast, the offers and the calls, but change nothing." },
  { role: "farmer", icon: "phone", name: "Farmer", go: "Open the call client",
    desc: "Answer the agent's phone calls in this browser, playing the farmer." },
];

// Only ever return to one of our own pages: a route ("/setup") or an old file name ("setup.html").
function returnTo(next) {
  if (OLD_URLS[next]) return OLD_URLS[next];
  return ["/", "/setup", "/approvals"].includes(next) ? next : "/";
}

export default function Login() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(params.get("expired") ? "Your session ended. Pick a role to continue." : "");
  const current = getSession();
  useEffect(() => {
    document.body.className = "login-page";
    document.title = "Sign in · Harvest-Call";
  }, []);

  const pick = async (role) => {
    setBusy(true);
    setNotice("");
    try {
      await signIn(role);
      // The call client is a separate (vanilla) page; planner pages stay in the app.
      if (role === "farmer") location.assign("/call.html");
      else navigate(returnTo(params.get("next") || "/"), { replace: true });
    } catch (err) {
      setNotice(err.status ? err.message : `${err.message || "Cannot reach the server."} Check the backend URL in config.js.`);
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <div className="login-head">
        <div className="brand"><span className="mark"><Icon name="leaf" /></span>Harvest-Call</div>
        <h1>Choose how you want to enter</h1>
        <p className="muted">Demo mode: there is no password, just pick a role. All data is synthetic.</p>
      </div>
      {notice && <p className="banner error" role="alert">{notice}</p>}
      <div className="roles" role="group" aria-label="Roles">
        {ROLES.map((r) => (
          <button key={r.role} className={`role-tile ${r.role === "planner" ? "main" : ""}`} disabled={busy} onClick={() => pick(r.role)}>
            <span className="role-icon"><Icon name={r.icon} size={20} /></span>
            <span className="role-name">{r.name}</span>
            <span className="role-desc">{r.desc}</span>
            <span className="role-go">{r.go}</span>
          </button>
        ))}
      </div>
      {current && <p className="small muted">Currently signed in as {current.name} ({ROLE_LABEL[current.role]}). Picking a role below switches you.</p>}
    </main>
  );
}
