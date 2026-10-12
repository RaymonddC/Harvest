import { motion } from "motion/react";
import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import SignInForm from "../components/SignInForm.jsx";
import { cfg, getSession, OLD_URLS, roleLabel } from "../lib.js";
import { useLive } from "../live.jsx";
import { Icon } from "../ui.jsx";

// What the product does, in the order it happens.
const STEPS = [
  "Calls each farmer in their own language",
  "Updates the weekly forecast as the answers come in",
  "Fills short weeks, and asks you before any deal",
];

// Where the "calls" light up on the field drawing (percent of the panel), and when.
const CALLS = [[22, 30, 0], [68, 22, 1.4], [40, 58, 2.6], [80, 64, 0.7], [16, 78, 3.4], [56, 86, 2]];

// Only ever return to one of our own pages: a route ("/setup") or an old file name ("setup.html").
function returnTo(next) {
  if (OLD_URLS[next]) return OLD_URLS[next];
  return ["/", "/setup", "/approvals", "/users"].includes(next) ? next : "/";
}

// Rows of palms seen from above, with calls ringing out across them now and then.
function Field() {
  return (
    <div className="ls-field" aria-hidden="true">
      {CALLS.map(([x, y, delay]) => (
        <span key={`${x}-${y}`} className="ls-call" style={{ left: `${x}%`, top: `${y}%`, animationDelay: `${delay}s` }}>
          <i style={{ animationDelay: `${delay}s` }} /><i style={{ animationDelay: `${delay + 0.6}s` }} />
        </span>
      ))}
    </div>
  );
}

const rise = (i) => ({ initial: { opacity: 0, y: 12 }, animate: { opacity: 1, y: 0 },
  transition: { duration: 0.45, delay: 0.08 * i, ease: [0.2, 0.8, 0.2, 1] } });

// Left: what Harvest-Call is, with a few live figures. Right: the sign-in form.
export default function Login() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { state } = useLive();
  const current = getSession();
  useEffect(() => {
    document.body.className = "login-page";
    document.title = "Sign in · Harvest-Call";
  }, []);
  // The call client is a separate (vanilla) page; everyone else stays in the app.
  const done = (session) => {
    if (session.role === "farmer") location.assign("/call.html");
    else navigate(returnTo(params.get("next") || "/"), { replace: true });
  };

  const farmers = state ? state.farmers.filter((f) => f.type !== "supplier").length : null;
  const weeks = state ? state.forecast.length : null;
  const gap = state ? [...state.forecast].sort((a, b) => a.week - b.week).find((r) => r.is_gap) : null;

  return (
    <main className="login-split">
      <section className="login-story" aria-label="About Harvest-Call">
        <Field />
        <div className="brand"><span className="mark"><Icon name="leaf" /></span>Harvest-Call</div>
        <div className="ls-body">
          <motion.h2 {...rise(0)}>An AI agent phones your farmers and keeps the supply forecast up to date.</motion.h2>
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
        <p className="ls-foot">{cfg.millName} · synthetic data</p>
      </section>

      <section className="login-pick" aria-labelledby="login-title">
        <motion.div className="lp-head" {...rise(0)}>
          <h1 id="login-title">Sign in</h1>
          <p className="muted">Welcome back. Sign in to plan this week's supply.</p>
        </motion.div>

        <motion.div {...rise(1)}>
          <SignInForm onSignedIn={done} initialError={params.get("expired") ? "Your session ended. Sign in again." : ""} />
        </motion.div>

        <motion.p className="small muted" {...rise(3)}>No microphone, or nobody to play the farmer? <a href="/call.html?sample=1">Watch a sample call</a>.</motion.p>
        {current && <p className="small muted">Signed in as {current.name} ({roleLabel(current)}). Signing in again switches you.</p>}
      </section>
    </main>
  );
}
