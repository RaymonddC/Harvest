import { motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import Logo from "../components/Logo.jsx";
import SignInForm from "../components/SignInForm.jsx";
import { campaignsOf, inCampaign } from "../campaigns.jsx";
import { api, getSession, OLD_URLS, roleLabel, signIn } from "../lib.js";
import { useLive } from "../live.jsx";
import { Icon, Spinner } from "../ui.jsx";

const ROLE_ICON = { planner: "forecast", coordinator: "setup", viewer: "eye", farmer: "phone" };
// One line per role on the tiles: what that person gets to do (the full descriptions repeat the role name).
const ROLE_LINE = {
  planner: "Sees the forecast, sets price limits and approves deals.",
  coordinator: "Runs campaigns and keeps the farmer list.",
  viewer: "Watches the forecast and calls, changes nothing.",
  farmer: "Answers the agent's call in this browser.",
};
const ROLE_GO = { farmer: "Answer a call" };
const UNREACHABLE = "Can't reach Harvest-Call right now. Try again in a moment.";
// The server is down or config.js points at the wrong backend: say so plainly, and leave the detail for developers.
function reachError(err) {
  if (err.status) return err.message;
  console.warn("Harvest-Call: cannot reach the backend. Check the backend URL in config.js.", err);
  return UNREACHABLE;
}

// What the product does, in the order it happens.
const STEPS = [
  "Calls each farmer in their own language",
  "Updates the weekly forecast as the answers come in",
  "Fills short weeks, and asks you before any deal",
];


// Only ever return to one of our own pages: a route ("/setup") or an old file name ("setup.html").
function returnTo(next) {
  if (OLD_URLS[next]) return OLD_URLS[next];
  return ["/", "/setup", "/approvals", "/users"].includes(next) ? next : "/";
}

// A 3D phone playing a call on its screen: ringing, the conversation (lines from the recorded sample call), then
// the harvest it saved (components/PhoneScene.js, Three.js, loaded only here). Still with "reduce motion"; left out
// when the browser has no WebGL, and on narrow screens, where the panel is a short header strip.
const NARROW = "(max-width: 860px)";
function Field({ brandRef, cardRef }) {
  const ref = useRef(null);
  const [failed, setFailed] = useState(() => window.matchMedia(NARROW).matches);
  useEffect(() => {
    if (failed) return undefined;
    let stop = null, alive = true;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    import("../components/PhoneScene.js")
      .then(({ startPhone }) => {
        if (!alive || !ref.current) return;
        // The phone fills the space between the logo and the text card, its lower part behind the see-through card.
        const fit = () => {
          const top = (brandRef.current?.offsetTop || 0) + (brandRef.current?.offsetHeight || 0) + 16;
          const card = cardRef.current;
          const bottom = card ? card.offsetTop + card.offsetHeight * 0.4 : ref.current.clientHeight;
          return { top, bottom };
        };
        stop = startPhone(ref.current, { still, fit, watch: [cardRef.current] });
      })
      .catch(() => setFailed(true));
    return () => { alive = false; stop?.(); };
  }, [failed]);
  if (failed) return null;
  return <canvas ref={ref} className="ls-scene" aria-hidden="true" />;
}

const rise = (i) => ({ initial: { opacity: 0, y: 12 }, animate: { opacity: 1, y: 0 },
  transition: { duration: 0.45, delay: 0.08 * i, ease: [0.2, 0.8, 0.2, 1] } });

// Left: what Harvest-Call is, with a few live figures. Right: the sign-in form.
export default function Login() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { state } = useLive();
  const current = getSession();
  const brandRef = useRef(null);
  const cardRef = useRef(null);
  // The people to pick from: the built-in demo accounts (they share the demo password).
  const [people, setPeople] = useState(null);
  const [demoPassword, setDemoPassword] = useState("");
  const [busy, setBusy] = useState(null);
  // "Sign in with a username" open: the people are hidden so the form is the only thing to do. Opens by itself
  // when there are no demo people to pick.
  const [byName, setByName] = useState(false);
  const expired = !!params.get("expired");
  const [notice, setNotice] = useState(expired ? "Your session ended. Pick a person to continue." : "");
  const [loadFailed, setLoadFailed] = useState(false);
  const load = useCallback(() => {
    setLoadFailed(false);
    setPeople(null);
    api("/api/auth/demo", { method: "GET", auth: false })
      .then((r) => {
        const accounts = r.accounts || [];
        setPeople(accounts);
        setDemoPassword(r.password || "");
        if (!accounts.length) { setByName(true); if (expired) setNotice("Your session ended. Sign in again."); }
      })
      .catch((err) => { setPeople([]); setLoadFailed(true); reachError(err); });
  }, [expired]);
  useEffect(load, [load]);
  useEffect(() => {
    document.body.className = "login-page";
    document.title = "Sign in · Harvest-Call";
  }, []);
  // The call client is a separate (vanilla) page; everyone else stays in the app.
  const done = (session) => {
    if (session.role === "farmer") location.assign("/call.html");
    else navigate(returnTo(params.get("next") || "/"), { replace: true });
  };
  const pick = async (person) => {
    setBusy(person.id);
    setNotice("");
    try {
      done(await signIn(person.username, demoPassword));
    } catch (err) {
      setNotice(reachError(err));
      setBusy(null);
    }
  };

  // The main campaign's figures (the forecast holds every campaign's weeks; counting them all said "17 weeks").
  const camp = campaignsOf(state)[0];
  const rows = state && camp ? inCampaign(state, state.forecast, camp.id).sort((a, b) => a.week - b.week) : [];
  const farmers = state && camp ? inCampaign(state, state.farmers, camp.id).filter((f) => f.type !== "supplier").length : null;
  const weeks = rows.length;
  const gap = rows.find((r) => r.is_gap);

  return (
    <main className="login-split">
      <section className="login-story" aria-label="About Harvest-Call">
        <Field brandRef={brandRef} cardRef={cardRef} />
        <div className="brand" ref={brandRef}><Logo size={36} />Harvest-Call</div>
        <div className="ls-card" ref={cardRef}>
        <div className="ls-body">
          <motion.p className="ls-title" {...rise(0)}>An AI agent phones your farmers and keeps the supply forecast up to date.</motion.p>
          <ol className="ls-steps">
            {STEPS.map((s, i) => <motion.li key={s} {...rise(i + 1)}><span className="ls-n">{i + 1}</span>{s}</motion.li>)}
          </ol>
        </div>
        {state && (
          <motion.dl className="ls-facts" {...rise(4)}>
            <div><dt>Farmers</dt><dd className="num">{farmers}</dd></div>
            <div><dt>Forecast</dt><dd className="num">{weeks} weeks</dd></div>
            <div><dt>This week</dt><dd>{gap ? `Week ${gap.week} short` : "On track"}</dd></div>
          </motion.dl>
        )}
        </div>
      </section>

      {/* Wilbert's "Who is signing in?" picker (until 12 Oct): one tile per person, one click signs in with the demo
          password; real accounts sign in with a username below. */}
      <section className="login-pick picker" aria-labelledby="login-title">
        <motion.div className="lp-head" {...rise(0)}>
          <h1 id="login-title">Who is signing in?</h1>
          <p className="muted">{byName ? "Sign in with your own username and password." : "Demo mode: just pick a person. What each person can do depends on their role. All data is synthetic."}</p>
        </motion.div>
        {current && <p className="small muted">Signed in as {current.name} ({roleLabel(current)}). Picking someone switches you.</p>}
        {notice && !loadFailed && <p className="banner error" role="alert">{notice}</p>}
        {loadFailed && (
          <div className="banner error lp-retry" role="alert">
            <span>{UNREACHABLE}</span>
            <button type="button" className="btn small" onClick={load}>Try again</button>
          </div>
        )}
        {!byName && people === null && (
          <div className="roles" aria-busy="true">
            <span className="sr-only">Loading the people…</span>
            {[0, 1, 2, 3].map((i) => <div key={i} className="role-tile skeleton" aria-hidden="true"><i /><i /><i /></div>)}
          </div>
        )}
        {!byName && people?.length > 0 && <motion.div className="roles" role="group" aria-label="People" {...rise(1)}>
          {people.map((p, i) => (
            <button key={p.id} type="button" className={`role-tile ${i === 0 ? "main" : ""}`} disabled={!!busy} aria-busy={busy === p.id || undefined}
              aria-label={`Sign in as ${p.name}, ${p.role_label}`} aria-describedby={`role-line-${p.id}`} onClick={() => pick(p)}>
              <span className="role-icon"><Icon name={ROLE_ICON[p.role] || "users"} size={20} /></span>
              <span className="role-name">{p.name} <span className="role-chip">{p.role_label}</span>{i === 0 && <span className="role-start">Start here</span>}</span>
              <span className="role-desc" id={`role-line-${p.id}`}>{ROLE_LINE[p.role] || p.description}</span>
              <span className="role-go">{busy === p.id ? <><Spinner />Signing in…</> : ROLE_GO[p.role] || "Open the overview"}</span>
            </button>
          ))}
        </motion.div>}
        <details className="own-account" open={byName} onToggle={(e) => setByName(e.currentTarget.open)}>
          <summary aria-label={byName ? "Back to the people" : "Sign in with a username (hides the people)"}>{byName ? "Back to the people" : "Sign in with a username"}</summary>
          <SignInForm onSignedIn={done} noDemo autoFocus={false} />
        </details>
      </section>
    </main>
  );
}
