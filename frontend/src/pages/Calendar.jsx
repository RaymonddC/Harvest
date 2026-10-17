import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useCrop } from "../campaigns.jsx";
import { api, fmtKg, fmtT, KIND_WORD } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { SegToggle } from "../ui.jsx";

// What happens on which day: calls made and planned (and the weekly Monday calls), harvests (the next round
// each farmer gave, and later rounds projected from how often they harvest), deal delivery weeks, weighbridge
// deliveries, and each campaign's planning weeks (amber when short). From GET /api/calendar.
const TYPES = [
  { key: "call", label: "Calls", also: ["call_plan"] },
  { key: "harvest", label: "Harvests" },
  { key: "deal", label: "Deals & deliveries", also: ["delivery"] },
  { key: "week", label: "Campaign weeks", also: ["campaign_start", "campaign_end"] },
];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const mondayOf = (d) => addDays(d, -((d.getDay() + 6) % 7));
const OUTCOME = { completed: "done", declined: "declined", no_answer: "no answer", busy: "busy", dropped: "dropped" };

function label(e, names) {
  switch (e.type) {
    case "call": return `${e.planned ? "Waiting: " : ""}${e.farmer_name}, ${(KIND_WORD[e.kind] || "call").replace(" call", "")}${e.outcome && OUTCOME[e.outcome] ? `, ${OUTCOME[e.outcome]}` : ""}`;
    case "call_plan": return `Weekly calls, ${names[e.campaign_id] || ""}`;
    case "campaign_start": return `${names[e.campaign_id] || "Campaign"} starts`;
    case "campaign_end": return `${names[e.campaign_id] || "Campaign"} ends`;
    case "harvest": return `${e.farmer_name}, ${fmtT(e.kg)} t${e.projected ? " (projected)" : e.confidence === "unsure" ? " (unsure)" : ""}`;
    case "deal": return `Deal, ${e.farmer_name}, ${fmtT(e.kg)} t${e.status === "approved" ? "" : ", waiting"}`;
    case "delivery": return `Delivered, ${e.farmer_name}, ${fmtT(e.kg)} t`;
    default: return "";
  }
}
// One chip per kind and day: a single event by name, several as a count and total ("12 t, 9 harvests").
const GROUP_WORD = { call: ["call", "calls"], harvest: ["harvest", "harvests"], deal: ["deal", "deals"], delivery: ["delivery", "deliveries"] };
function chips(evs, names) {
  const groups = [];
  for (const e of evs) {
    const g = groups.find((x) => x.type === e.type && !["call_plan", "campaign_start", "campaign_end"].includes(e.type));
    if (g) g.items.push(e); else groups.push({ type: e.type, items: [e] });
  }
  return groups.map((g) => {
    if (g.items.length === 1) return { text: label(g.items[0], names), cls: cls(g.items[0]) };
    const [one, many] = GROUP_WORD[g.type] || ["event", "events"];
    const kg = g.items.reduce((n, e) => n + (e.kg || 0), 0);
    const waiting = g.items.filter((e) => e.planned || (e.type === "deal" && e.status !== "approved")).length;
    const allProjected = g.items.every((e) => e.projected);
    return { text: `${kg ? `${fmtT(kg)} t, ` : ""}${g.items.length} ${g.items.length === 1 ? one : many}${waiting ? `, ${waiting} waiting` : ""}${allProjected ? " (projected)" : ""}`,
      cls: `${g.type} ${allProjected ? "projected" : ""} ${waiting === g.items.length && g.type === "call" ? "planned" : ""}` };
  });
}
const cls = (e) => (e.type.startsWith("campaign_") ? "campaign" : e.type === "call" ? (e.planned ? "call planned" : "call")
  : e.type === "harvest" ? `harvest ${e.projected ? "projected" : ""}` : e.type === "deal" ? `deal ${e.status}` : e.type);

export default function Calendar() {
  const { state } = useLive();
  const { cid, campaign } = useCrop();
  const [params] = useSearchParams();
  const asked = /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") || "") ? new Date(`${params.get("date")}T00:00:00`) : null;
  const [month, setMonth] = useState(() => { const d = asked || new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });
  const [scope, setScope] = useState("one"); // "one": the picked campaign, "all": every campaign
  const [shownTypes, setShownTypes] = useState(() => new Set(TYPES.map((t) => t.key)));
  const [data, setData] = useState(null);
  const [day, setDay] = useState(() => iso(asked || new Date()));
  // A day outside the month on screen has no data loaded: move the selection into the month (today if it is there).
  useEffect(() => {
    if (new Date(`${day}T00:00:00`).getMonth() === month.getMonth()) return;
    const now = new Date();
    setDay(iso(now.getMonth() === month.getMonth() && now.getFullYear() === month.getFullYear() ? now : month));
  }, [month]); // eslint-disable-line react-hooks/exhaustive-deps
  const [error, setError] = useState("");

  const gridStart = mondayOf(month);
  const gridEnd = addDays(gridStart, 41);
  // Refetch when anything the calendar shows changes.
  const key = state ? JSON.stringify([state.calls.map((c) => [c.id, c.status]), state.harvests.map((h) => [h.id, h.ready_date, h.kg, h.every_days]),
    state.offers.map((o) => [o.id, o.status]), state.forecast.map((r) => [r.id, r.is_gap]), state.campaigns.map((c) => [c.id, c.weekly?.enabled]),
    state.farmers.length]) : "";
  useEffect(() => {
    if (!state) return undefined;
    let live = true;
    const q = `start=${iso(gridStart)}&end=${iso(gridEnd)}${scope === "one" ? `&campaign=${encodeURIComponent(cid)}` : ""}`;
    const t = setTimeout(() => api(`/api/calendar?${q}`, { method: "GET" })
      .then((r) => { if (live) { setData(r); setError(""); } })
      .catch((e) => { if (live) setError(e.message || "Could not load the calendar."); }), 250);
    return () => { live = false; clearTimeout(t); };
  }, [key, month.getTime(), scope, cid]); // eslint-disable-line react-hooks/exhaustive-deps

  const allowed = useMemo(() => new Set(TYPES.filter((t) => shownTypes.has(t.key)).flatMap((t) => [t.key, ...(t.also || [])])), [shownTypes]);
  const byDay = useMemo(() => {
    const m = {};
    for (const e of data?.events || []) if (e.type !== "week" && allowed.has(e.type)) (m[e.date] ||= []).push(e);
    return m;
  }, [data, allowed]);
  // The planning weeks, by their Monday: amber when short (in every campaign shown).
  const weeks = useMemo(() => {
    const m = {};
    if (!allowed.has("week")) return m;
    for (const e of data?.events || []) if (e.type === "week") (m[e.date] ||= []).push(e);
    return m;
  }, [data, allowed]);
  const names = data?.campaigns || {};
  const toggle = (k) => { const n = new Set(shownTypes); if (n.has(k)) n.delete(k); else n.add(k); setShownTypes(n); };
  const today = iso(new Date());
  const dayEvents = byDay[day] || [];
  const dayWeek = Object.entries(weeks).find(([start]) => start <= day && day <= iso(addDays(new Date(start + "T00:00:00"), 6)))?.[1] || [];

  const head = (
    <div className="page-head">
      <div>
        <h1>Calendar</h1>
        <p>Calls, harvests, deals and deliveries by day{scope === "one" && campaign.label ? `, for ${campaign.label}` : ", for every campaign"}.</p>
      </div>
      <SegToggle label="Which campaigns" options={[["one", "This campaign"], ["all", "All campaigns"]]} value={scope} onChange={setScope} />
    </div>
  );

  return (
    <Shell title="Calendar" head={head}>
      <div className="cal-layout">
        <section className="card cal-card" aria-label="Month">
          <div className="cal-bar">
            <div className="cal-nav">
              <button type="button" className="btn sm" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>‹</button>
              <h2>{month.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</h2>
              <button type="button" className="btn sm" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>›</button>
              <button type="button" className="btn sm ghost" onClick={() => { const d = new Date(); setMonth(new Date(d.getFullYear(), d.getMonth(), 1)); setDay(iso(d)); }}>Today</button>
            </div>
            <div className="cal-types" role="group" aria-label="Show">
              {TYPES.map((t) => (
                <label key={t.key} className={`cal-type t-${t.key}`}>
                  <input type="checkbox" checked={shownTypes.has(t.key)} onChange={() => toggle(t.key)} /><i aria-hidden="true" />{t.label}
                </label>
              ))}
            </div>
          </div>
          {error && <p className="banner error" role="alert">{error}</p>}
          <div className="cal-grid" role="grid" aria-label="Days">
            {WEEKDAYS.map((w) => <div key={w} className="cal-wd" role="columnheader">{w}</div>)}
            {Array.from({ length: 6 }, (_, r) => {
              const monday = iso(addDays(gridStart, r * 7));
              const wk = weeks[monday] || [];
              const short = wk.some((w) => w.is_gap);
              return (
                <div key={monday} className={`cal-row ${wk.length ? "planned" : ""} ${short ? "short" : ""}`} role="row">
                  {wk.length > 0 && <span className="cal-weektag">{short ? `${wk.filter((w) => w.is_gap).map((w) => w.label).join(", ")} short` : wk.map((w) => w.label).filter((v, i, a) => a.indexOf(v) === i).join(", ")}</span>}
                  {Array.from({ length: 7 }, (_, c) => {
                    const d = addDays(gridStart, r * 7 + c);
                    const k = iso(d);
                    const evs = byDay[k] || [];
                    const out = d.getMonth() !== month.getMonth();
                    return (
                      <button key={k} type="button" role="gridcell" aria-selected={k === day}
                        className={`cal-day ${out ? "out" : ""} ${k === today ? "today" : ""} ${k === day ? "sel" : ""}`}
                        aria-label={`${d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}: ${evs.length} ${evs.length === 1 ? "event" : "events"}`}
                        onClick={() => setDay(k)}>
                        <span className="cal-num">{d.getDate()}</span>
                        {chips(evs, names).slice(0, 4).map((c, i) => <span key={i} className={`cal-chip ${c.cls}`}>{c.text}</span>)}
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </section>
        <aside className="card cal-day-card" aria-live="polite" aria-label="The day">
          <h2>{new Date(day + "T00:00:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}</h2>
          {dayWeek.map((w) => (
            <p key={`${w.campaign_id}-${w.label}`} className={`cal-weekline ${w.is_gap ? "short" : ""}`}>
              {scope === "all" ? `${names[w.campaign_id] || ""}, ` : ""}{w.label}: {fmtT(w.expected_kg)} of {fmtT(w.target_kg)} t expected{w.is_gap ? `, ${fmtT(w.gap_kg)} t short` : ""}
            </p>
          ))}
          {dayEvents.length ? (
            <ul className="cal-list">
              {dayEvents.map((e, i) => (
                <li key={i} className={cls(e)}>
                  <i aria-hidden="true" />
                  <div>
                    <b>{label(e, names)}</b>
                    <small className="muted">
                      {[e.time, scope === "all" && names[e.campaign_id], e.type === "deal" && e.price_per_kg ? `${fmtKg(e.price_per_kg)} ${e.currency}/kg` : null,
                        e.type === "deal" && e.status === "approved" ? (e.confirmed_by_voice ? "confirmed by voice" : "confirmation call waiting") : null,
                        e.type === "call_plan" ? (e.channel === "twilio" ? "rings the farmers' phones" : "queued for the browser") : null,
                        e.type === "harvest" && e.projected ? "from how often they harvest" : null].filter(Boolean).join(", ")}
                    </small>
                  </div>
                </li>
              ))}
            </ul>
          ) : <p className="muted small">Nothing on this day{shownTypes.size < TYPES.length ? " (some kinds are hidden)" : ""}.</p>}
        </aside>
      </div>
    </Shell>
  );
}
