import { motion } from "motion/react";
import { useEffect } from "react";
import { Link, Navigate, NavLink, useLocation } from "react-router-dom";
import { can, cfg, getSession, PAGES, roleLabel } from "./lib.js";
import { useLive } from "./live.jsx";
import { Avatar, Icon } from "./ui.jsx";

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
