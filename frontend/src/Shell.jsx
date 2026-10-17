import { motion } from "motion/react";
import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, useLocation, useNavigate } from "react-router-dom";
import { can, FLOW, fmtT, getSession, OVERVIEW, PAGES, SETTINGS } from "./lib.js";
import AccountMenu from "./components/AccountMenu.jsx";
import Logo from "./components/Logo.jsx";
import CropSwitcher from "./components/CropSwitcher.jsx";
import { campaignFor, inCampaign, useCrop } from "./campaigns.jsx";
import NextStep from "./components/NextStep.jsx";
import { nextAutoText, todoItems } from "./todo.js";
import { useUnsaved } from "./dialogs.jsx";
import { useLive } from "./live.jsx";
import { Dialog, DialogClose, Icon } from "./ui.jsx";

// This week at a glance, under the page links: is calling on, is a week short, does anything
// wait for a decision. Hidden on narrow screens, where the sidebar is a single row.
// The first few items of the campaign's To do list (todo.js), each the problem and the next action, linking to
// where it is done. The Overview page shows the whole list.
function WeekCard({ state }) {
  const { cid } = useCrop();
  if (!state) return null;
  const campaign = campaignFor(state, cid);
  const items = todoItems(state, cid);
  return (
    <div className="week-card" aria-label="To do">
      <span className="wc-title">To do for {campaign.label || "this campaign"}</span>
      {items.length ? items.slice(0, 4).map((it) => (
        <Link key={it.key} className={`wc-item ${it.tone}`} to={it.to}>
          <i className="wc-dot" />
          <span><b>{it.what}</b><small>{it.next}</small></span>
        </Link>
      )) : (
        <div className="wc-item done"><i className="wc-dot" /><span><b>Nothing waiting</b><small>Every week is on track and every farmer has answered{nextAutoText(campaign) ? `; ${nextAutoText(campaign)}` : ""}.</small></span></div>
      )}
      {items.length > 4 && <Link className="wc-more" to="/">All {items.length} on the Overview</Link>}
    </div>
  );
}

// A short checklist for someone seeing the demo cold. Each step ticks from the live data, and the
// first open one links to the page where it is done. Collapsible; the choice is remembered.
const GUIDE_KEY = "harvestGuideOpen";
function DemoGuide({ state }) {
  const [open, setOpen] = useState(() => {
    const phone = window.matchMedia("(max-width: 640px)").matches; // on a phone it starts closed, to leave room for the page
    try { const saved = localStorage.getItem(GUIDE_KEY); return saved === null ? !phone : saved !== "0"; } catch { return !phone; }
  });
  if (!state) return null;
  const { calls, offers } = state;
  const anyRunning = state.campaigns.some((c) => c.status === "running"); // the guide follows the whole mill, not one crop
  const steps = [
    ["Check the farmers and the price range", "/setup", state.farmers.length > 0 && state.limits.length > 0],
    ["Start calling", "/setup", anyRunning || calls.some((c) => c.status !== "queued")],
    ["Answer a call as the farmer", "/calls", calls.some((c) => ["done", "on_call"].includes(c.status))],
    ["Fill the gap: gap-fill calls or the rival quote", "/forecast", offers.length > 0],
    ["Approve the offers", "/approvals", offers.some((o) => o.status === "approved")],
    ["Answer the confirmation call", "/calls", offers.some((o) => o.confirmed_by_voice)],
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

const OVERVIEW_PATHS = PAGES.filter((p) => p.step === OVERVIEW.id).map((p) => p.to);

// Which step of the flow this page is, what it is for, and the page that usually comes next.
function FlowLine({ pathname, go }) {
  const page = PAGES.find((p) => p.to === pathname);
  if (!page) return null;
  const step = FLOW.find((g) => g.id === page.step);
  const next = PAGES.find((p) => p.key === page.next);
  return (
    <div className="flow-line" role="note">
      {step ? <span className="flow-step"><b>{step.n}</b>Step {step.n} of {FLOW.length}: {step.label}</span>
        : <span className="flow-step settings">{page.step === OVERVIEW.id ? OVERVIEW.label : SETTINGS.label}</span>}
      <span className="flow-text">{page.line}</span>
      {next && <Link className="flow-next" to={next.to} onClick={(e) => go(e, next.to)}>Next: {next.label}</Link>}
    </div>
  );
}

// Keyboard shortcuts for people who use the app every day. Typing in a box never triggers them.
const SHORTCUTS = [["g then o", "Overview"], ["g then f", "Live forecast"], ["g then s", "Campaign"], ["g then m", "Farmers"], ["g then c", "Calls"],
  ["g then k", "Calendar"], ["g then g", "Agent"], ["g then a", "Approvals"], ["g then u", "Users"],
  ["/", "Search the farmer list"], ["?", "Show these shortcuts"]];
const GO = { o: "/", f: "/forecast", s: "/setup", m: "/farmers", c: "/calls", k: "/calendar", g: "/agent", a: "/approvals", u: "/users" };
const PAGE_OF = { "/": "overview", "/forecast": "forecast", "/setup": "setup", "/farmers": "farmers", "/calls": "calls", "/calendar": "calendar",
  "/agent": "agent", "/approvals": "approvals", "/users": "users" };

// Sidebar (phone: top row plus a bottom tab bar, from app.css), a top bar holding the page
// heading, and the banners for live-data trouble and view-only sessions.
// The header's next-step button shows only where the page is about moving the work on; pages with their own main
// action (Farmers, Campaign, Approvals) and settings pages do without it, so there is one main button per page.
const NEXT_STEP_ON = ["/", "/forecast", "/calendar", "/calls"];

export default function Shell({ title, head, children }) {
  const { state, status } = useLive();
  const { pathname } = useLocation();
  const session = getSession();
  const loading = !state && status !== "error";
  const navigate = useNavigate();
  const { cid } = useCrop();
  const { guard } = useUnsaved();
  const waitingNow = state ? state.offers.filter((o) => ["pending", "escalated"].includes(o.status)).length : 0;
  // The tab title counts offers waiting for a decision, so it shows even in a background tab.
  useEffect(() => { document.title = `${waitingNow ? `(${waitingNow}) ` : ""}${title} · Harvest-Call`; }, [title, waitingNow]);
  // Moving between pages asks first when a form has unsaved changes.
  const go = async (e, to) => {
    if (e) e.preventDefault();
    if (await guard()) navigate(to);
  };
  const [help, setHelp] = useState(false);
  // Wide screens: the sidebar can shrink to its icons; the choice is remembered in this browser.
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("harvestNavCollapsed") === "1"; } catch { return false; } });
  const toggleNav = () => {
    setCollapsed(!collapsed);
    try { localStorage.setItem("harvestNavCollapsed", collapsed ? "0" : "1"); } catch { /* storage blocked: lasts this visit */ }
  };
  useEffect(() => {
    let g = 0;
    const onKey = (e) => {
      const t = e.target;
      if (e.ctrlKey || e.metaKey || e.altKey || t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (document.querySelector("[role=dialog]")) return; // a modal is open: leave the keys alone
      if (e.key === "?") { e.preventDefault(); setHelp(true); return; }
      if (e.key === "/") {
        const box = document.querySelector('input[type="search"]');
        if (box) { e.preventDefault(); box.focus(); }
        return;
      }
      if (e.key === "g") { g = Date.now(); return; }
      if (Date.now() - g < 1200 && GO[e.key]) { g = 0; go(null, GO[e.key]); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // The top bar tightens once the page has scrolled. Two thresholds, far apart: tightening makes the
  // bar about 60px shorter, which moves the scroll position, and one threshold would then flip it
  // back and forth (the bar shook near the top of the page).
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled((was) => (was ? window.scrollY > 8 : window.scrollY > 96));
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    document.body.className = `app ${loading ? "loading" : ""}`.trim(); // grey placeholders until the first state
  }, [loading]);
  if (!session) return <Navigate to={`/login?next=${encodeURIComponent(pathname)}`} replace />;

  const waiting = state ? inCampaign(state, state.offers, cid).filter((o) => ["pending", "escalated"].includes(o.status)).length : 0;
  return (
    <>
      <aside className={`side ${collapsed ? "collapsed" : ""}`}>
        <div className="side-top">
          <Link className="brand" to="/" onClick={(e) => go(e, "/")} title="Harvest-Call"><Logo size={32} /><span className="brand-name">Harvest-Call</span></Link>
          <button type="button" className="nav-toggle" onClick={toggleNav} aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand the menu" : "Collapse the menu"} title={collapsed ? "Expand the menu" : "Collapse the menu"}>
            <span aria-hidden="true">{collapsed ? "»" : "«"}</span>
          </button>
        </div>
        <CropSwitcher />
        {/* The middle scrolls on its own when it is taller than the window; the account stays below it. */}
        <div className="side-scroll">
        <nav aria-label="Planner pages">
          {/* One item for the Overview and its tabs (Summary, Forecast, Calendar): lit on any of them. */}
          <div className="nav-group overview" role="group" aria-label={OVERVIEW.label}>
            <Link to="/" onClick={(e) => go(e, "/")} title={collapsed ? OVERVIEW.label : undefined}
              className={OVERVIEW_PATHS.includes(pathname) ? "active" : ""} aria-current={OVERVIEW_PATHS.includes(pathname) ? "page" : undefined}>
              <Icon name="overview" /><span className="label">{OVERVIEW.label}</span>
            </Link>
          </div>
          {FLOW.map((g) => (
            <div key={g.id} className="nav-group" role="group" aria-labelledby={`nav-${g.id}`}>
              <span className="nav-step" id={`nav-${g.id}`}><b>{g.n}</b>{g.label}</span>
              {PAGES.filter((p) => p.step === g.id).map(({ key, to, label }) => (
                <NavLink key={key} to={to} end onClick={(e) => go(e, to)} title={collapsed ? label : undefined} aria-label={key === "approvals" && waiting ? `Approvals, ${waiting} waiting` : undefined}>
                  <Icon name={key} /><span className="label">{label}</span>
                  {key === "approvals" && waiting > 0 && <span className="count">{waiting}</span>}
                </NavLink>
              ))}
            </div>
          ))}
          <div className="nav-group settings" role="group" aria-labelledby="nav-settings">
            <span className="nav-step" id="nav-settings">{SETTINGS.label}</span>
            {PAGES.filter((p) => p.step === SETTINGS.id).map(({ key, to, label }) => (
              <NavLink key={key} to={to} end onClick={(e) => go(e, to)} title={collapsed ? label : undefined}>
                <Icon name={key} /><span className="label">{label}</span>
              </NavLink>
            ))}
          </div>
        </nav>
        <WeekCard state={state} />
        <DemoGuide state={state} />
        </div>
        <div className="side-foot"><AccountMenu session={session} /></div>
      </aside>
      <div className="workspace">
        <div className={`topbar ${scrolled ? "scrolled" : ""}`}>
          <div className="topbar-row">{head}{NEXT_STEP_ON.includes(pathname) && <NextStep page={PAGE_OF[pathname]} />}</div>
        </div>
        {/* No animation between pages: navigation is used all day, so the page simply swaps (pages are preloaded). */}
        <main className="page">
          {!session.capabilities?.length && (
            <div className="banner" role="note">View only. You can watch the forecast, offers and calls, but anything that changes data is blocked. Use Switch user to sign in as someone who can.</div>
          )}
          {status !== "live" && status !== "connecting" && (
            <div className={`banner ${status === "error" ? "error" : ""}`} role="status">
              {status === "error" ? "Cannot reach the live data. Check the backend URL in config.js, then reload." : "Reconnecting to live data…"}
            </div>
          )}
          {OVERVIEW_PATHS.includes(pathname) && (
            <nav className="ov-tabs" aria-label="Overview">
              {PAGES.filter((p) => p.step === OVERVIEW.id).map((p) => (
                <NavLink key={p.key} to={p.to} end onClick={(e) => go(e, p.to)}><Icon name={p.key} size={16} />{p.tab}</NavLink>
              ))}
            </nav>
          )}
          <FlowLine pathname={pathname} go={go} />
          {children}
        </main>
      </div>
      <Dialog open={help} onClose={() => setHelp(false)} title="Keyboard shortcuts">
        <dl className="shortcuts">
          {SHORTCUTS.map(([keys, what]) => (
            <div key={keys}><dt>{keys.split(" then ").map((k, i) => <span key={k}>{i > 0 && <small> then </small>}<kbd>{k}</kbd></span>)}</dt><dd>{what}</dd></div>
          ))}
        </dl>
        <DialogClose>Close</DialogClose>
      </Dialog>
    </>
  );
}
