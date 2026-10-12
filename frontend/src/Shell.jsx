import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, useLocation } from "react-router-dom";
import { can, cfg, fmtT, getSession, PAGES, roleLabel } from "./lib.js";
import { useLive } from "./live.jsx";
import { Avatar, Icon } from "./ui.jsx";

// This week at a glance, under the page links: is calling on, is a week short, does anything
// wait for a decision. Hidden on narrow screens, where the sidebar is a single row.
function WeekCard({ state }) {
  if (!state) return null;
  const campaign = state.campaigns.find((x) => x.id === "current") || {};
  const running = campaign.status === "running";
  const gap = [...state.forecast].sort((a, b) => a.week - b.week).find((r) => r.is_gap);
  const waiting = state.offers.filter((o) => ["pending", "escalated"].includes(o.status)).length;
  return (
    <div className="week-card" aria-label="This week">
      <span className="wc-title">This week</span>
      <div className="wc-row"><i className={`wc-dot ${running ? "on" : ""}`} />{running ? (campaign.kind === "gap_fill" ? "Gap-fill calls running" : "Calling farmers") : "No calls running"}</div>
      <div className="wc-row"><i className={`wc-dot ${gap ? "amber" : "on"}`} />{gap ? `Week ${gap.week} is ${fmtT(gap.gap_kg)} t short` : "Every week on track"}</div>
      {waiting > 0 && <Link className="wc-row wc-link" to="/approvals"><i className="wc-dot amber" />{waiting} waiting for a decision</Link>}
    </div>
  );
}

// A short checklist for someone seeing the demo cold. Each step ticks from the live data, and the
// first open one links to the page where it is done. Collapsible; the choice is remembered.
const GUIDE_KEY = "harvestGuideOpen";
function DemoGuide({ state }) {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem(GUIDE_KEY) !== "0"; } catch { return true; } });
  if (!state) return null;
  const { calls, offers } = state;
  const campaign = state.campaigns.find((x) => x.id === "current") || {};
  const steps = [
    ["Check the farmers and the price range", "/setup", state.farmers.length > 0 && state.limits.length > 0],
    ["Start calling", "/setup", campaign.status === "running" || calls.some((c) => c.status !== "queued")],
    ["Answer a call as the farmer", "/call.html", calls.some((c) => ["done", "on_call"].includes(c.status))],
    ["Fill the gap: gap-fill calls or the rival quote", "/", offers.length > 0],
    ["Approve the offers", "/approvals", offers.some((o) => o.status === "approved")],
    ["Answer the confirmation call", "/call.html", offers.some((o) => o.confirmed_by_voice)],
  ];
  const next = steps.findIndex((s) => !s[2]);
  const toggle = () => { setOpen(!open); try { localStorage.setItem(GUIDE_KEY, open ? "0" : "1"); } catch { /* storage blocked */ } };
  return (
    <section className="guide" aria-label="Demo guide">
      <button className="guide-toggle" type="button" aria-expanded={open} onClick={toggle}>Demo guide</button>
      {open && (
        <ol className="guide-steps">
          {steps.map(([label, to, done], i) => (
            <li key={label} className={done ? "done" : i === next ? "next" : ""}>
              <span className="tick" aria-hidden="true">{done ? "✓" : i + 1}</span>
              {i === next
                ? (to.endsWith(".html") ? <a href={to}>{label}<span className="sr-only"> (next step)</span></a> : <Link to={to}>{label}<span className="sr-only"> (next step)</span></Link>)
                : <span>{label}</span>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

// Sidebar (phone: top row plus a bottom tab bar, from app.css), a top bar holding the page
// heading, and the banners for live-data trouble and view-only sessions.
export default function Shell({ title, head, children }) {
  const { state, status } = useLive();
  const { pathname } = useLocation();
  const session = getSession();
  const loading = !state && status !== "error";
  useEffect(() => { document.title = `${title} · Harvest-Call`; }, [title]);
  useEffect(() => {
    document.body.className = `app ${loading ? "loading" : ""}`.trim(); // grey placeholders until the first state
  }, [loading]);
  if (!session) return <Navigate to={`/login?next=${encodeURIComponent(pathname)}`} replace />;

  const waiting = state ? state.offers.filter((o) => ["pending", "escalated"].includes(o.status)).length : 0;
  return (
    <>
      <aside className="side">
        <Link className="brand" to="/"><span className="mark"><Icon name="leaf" /></span>Harvest-Call</Link>
        <div className="workspace-card"><span>Workspace</span><b>{cfg.millName}</b></div>
        <nav aria-label="Planner pages">
          {PAGES.filter((p) => !p.need || can(p.need)).map(({ key, to, label }) => (
            <NavLink key={key} to={to} end aria-label={key === "approvals" && waiting ? `Approvals, ${waiting} waiting` : undefined}>
              <Icon name={key} /><span className="label">{label}</span>
              {key === "approvals" && waiting > 0 && <span className="count">{waiting}</span>}
            </NavLink>
          ))}
        </nav>
        <WeekCard state={state} />
        <DemoGuide state={state} />
        <div className="spacer" />
        <div className="planner">
          <Avatar name={session.name} cls="ink" />
          <div>
            <b>{session.name}</b>
            <span>{roleLabel(session)} · </span><Link to="/login">Switch user</Link>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <div className="topbar">{head}</div>
        {/* A short fade as each page opens. */}
        <motion.main className="page" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, ease: "easeOut" }}>
          {!session.capabilities?.length && (
            <div className="banner" role="note">View only. You can watch the forecast, offers and calls, but anything that changes data is blocked. Use Switch user to sign in as someone who can.</div>
          )}
          {status !== "live" && status !== "connecting" && (
            <div className={`banner ${status === "error" ? "error" : ""}`} role="status">
              {status === "error" ? "Cannot reach the live data. Check the backend URL in config.js, then reload." : "Reconnecting to live data…"}
            </div>
          )}
          {children}
        </motion.main>
      </div>
    </>
  );
}
