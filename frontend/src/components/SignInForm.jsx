import { motion, useAnimationControls } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { api, signIn } from "../lib.js";
import { Avatar, Icon, SubmitButton } from "../ui.jsx";

// Username and password, plus the built-in demo accounts (their shared password is shown so judges
// can get in with one click). Used by the sign-in page and by the Switch user dialog.
// onSignedIn(session) runs after a successful sign-in; exclude hides the account already signed in.
export default function SignInForm({ onSignedIn, exclude, initialError = "", autoFocus = true, submitLabel = "Sign in" }) {
  const shake = useAnimationControls();
  const passwordRef = useRef(null);
  const [form, setForm] = useState({ username: "", password: "" });
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);
  const [demo, setDemo] = useState({ password: "", accounts: [] });
  useEffect(() => { api("/api/auth/demo", { method: "GET", auth: false }).then(setDemo).catch(() => {}); }, []);

  const refuse = (message) => {
    setError(message);
    shake.start({ x: [0, -10, 10, -6, 6, 0], transition: { duration: 0.4 } }); // one shake when refused
  };
  const signInAs = async (username, password) => {
    setBusy(true);
    setError("");
    try {
      const session = await signIn(username, password);
      await onSignedIn(session);
    } catch (err) {
      refuse(err.status ? err.message : `${err.message || "Cannot reach the server."} Check the backend URL in config.js.`);
      if (err.status === 401) { setForm((f) => ({ ...f, password: "" })); passwordRef.current?.focus(); }
    } finally {
      setBusy(false);
    }
  };
  const submit = (e) => {
    e.preventDefault();
    if (!form.username.trim() || !form.password) return refuse("Enter your username and password.");
    return signInAs(form.username, form.password);
  };
  const accounts = demo.accounts.filter((a) => a.id !== exclude);

  return (
    <div className="signin">
      <motion.form className="lp-form" onSubmit={submit} noValidate animate={shake}>
        <label className="field">Username
          <input type="text" name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} autoFocus={autoFocus}
            value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} aria-invalid={!!error || undefined} />
        </label>
        <label className="field">Password
          <span className="pw">
            <input ref={passwordRef} type={show ? "text" : "password"} name="password" autoComplete="current-password"
              value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} aria-invalid={!!error || undefined} />
            <button type="button" className="pw-toggle" onClick={() => setShow(!show)} aria-pressed={show}
              aria-label={show ? "Hide password" : "Show password"}><Icon name="eye" size={18} /></button>
          </span>
        </label>
        {error && <p className="lp-error" role="alert">{error}</p>}
        <SubmitButton className="btn solid big block" busy={busy} busyText="Signing in…">{submitLabel}</SubmitButton>
      </motion.form>

      {accounts.length > 0 && (
        <div className="demo-box">
          <div className="demo-head">
            <span>Demo accounts</span>
            <span className="muted">password <code>{demo.password}</code></span>
          </div>
          <div className="demo-list">
            {accounts.map((a) => (
              <button key={a.id} type="button" className="demo-acc" disabled={busy} title={a.description}
                onClick={() => { setForm({ username: a.username, password: demo.password }); signInAs(a.username, demo.password); }}>
                <Avatar name={a.name} cls="sm" person />
                <span><b>{a.name}</b><small>{a.role_label}</small></span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
