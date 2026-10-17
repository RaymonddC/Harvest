import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import SignInForm from "../components/SignInForm.jsx";
import { campaignsOf, inCampaign } from "../campaigns.jsx";
import { cfg, getSession, OLD_URLS, roleLabel } from "../lib.js";
import { useLive } from "../live.jsx";
import { Icon } from "../ui.jsx";

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
function Field() {
  const ref = useRef(null);
  const [failed, setFailed] = useState(() => window.matchMedia(NARROW).matches);
  useEffect(() => {
    if (failed) return undefined;
    let stop = null, alive = true;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    import("../components/PhoneScene.js")
      .then(({ startPhone }) => { if (alive && ref.current) stop = startPhone(ref.current, { still }); })
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
  useEffect(() => {
    document.body.className = "login-page";
    document.title = "Sign in · Harvest-Call";
  }, []);
  // The call client is a separate (vanilla) page; everyone else stays in the app.
  const done = (session) => {
    if (session.role === "farmer") location.assign("/call.html");
    else navigate(returnTo(params.get("next") || "/"), { replace: true });
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
