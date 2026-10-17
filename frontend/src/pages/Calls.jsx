import { useEffect, useRef, useState } from "react";
import { inCampaign, useCrop } from "../campaigns.jsx";
import CallRecap from "../components/forecast/CallRecap.jsx";
import { callChip, fmtKg, KIND_WORD, plainPrice } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { Avatar, DownloadLink, Icon, Pill } from "../ui.jsx";

// What each farmer said on the agent's calls: one row per call with the harvest they gave (kilograms, ready date,
// firm or unsure, how often they harvest), any offer, and their answers to the planner's own questions. A row opens
// the recap with the transcript. The demo phone (the browser playing the farmer, when no phone line is set up) is a
// side panel, not the page.
const NOT_REACHED = ["no_answer", "busy", "failed", "canceled", "not_connected", "dropped"];
const FILTERS = [
  { key: "all", label: "All calls" },
  { key: "harvest", label: "Harvest given" },
  { key: "unsure", label: "Unsure" },
  { key: "missed", label: "Not reached" },
  { key: "offer", label: "Offer made" },
  { key: "waiting", label: "Waiting" },
];
const when = (c) => c.ended_at || c.started_at || c.created_at;
const fmtWhen = (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const day = (iso) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }) : "");

const showLive = (id) => {
  const el = document.getElementById(`live-${id}`);
  if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.focus({ preventScroll: true }); }
};
const mmss = (from) => {
  const s = Math.max(0, Math.round((Date.now() - new Date(from).getTime()) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

// The calls the agent is on right now: who, how long, the conversation as it happens (the service saves it about
// once a second) and what the agent has noted so far. The text is dropped when the call ends; the recap keeps the
// transcript only if the farmer agreed.
function LiveCalls({ calls, farmers }) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!calls.length) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [calls.length]);
  if (!calls.length) return null;
  return (
    <section className="live-calls" aria-label="Calls on now">
      {calls.map((c) => <LiveCard key={c.id} c={c} f={farmers.get(c.farmer_id) || {}} />)}
    </section>
  );
}

function LiveCard({ c, f }) {
  const box = useRef(null);
  const lines = c.live || [];
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [lines.length, lines[lines.length - 1]?.text]);
  const n = c.live_notes || {};
  const cap = n.captured;
  return (
    <article className="live-card card" id={`live-${c.id}`} tabIndex={-1} aria-label={`Live call with ${c.farmer_name}`}>
      <header className="live-head">
        <Avatar name={c.farmer_name} id={c.farmer_id} cls="sm" />
        <div><b>{c.farmer_name}</b><small>{[f.village, KIND_WORD[c.kind], c.channel === "twilio" ? "on their phone" : "on the demo phone"].filter(Boolean).join(", ")}</small></div>
        <span className="live-time"><span className="dot-live" aria-hidden="true" />{c.started_at ? mmss(c.started_at) : "connecting"}</span>
      </header>
      <div className="live-lines" ref={box} aria-live="polite">
        {lines.length ? lines.map((l, i) => (
          <p key={i} className={`live-line ${l.who}`}><span>{l.who === "agent" ? "Agent" : c.farmer_name}</span>{l.text}</p>
        )) : <p className="muted small">The call has just started. The conversation appears here as they speak.</p>}
      </div>
      {(cap || n.rail || n.offer_saved) && (
        <footer className="live-notes">
          {cap && <span><b>Harvest:</b> {cap.kg != null ? `${Number(cap.kg).toLocaleString("en-US")} kg` : ""}{cap.ready ? `, ${cap.ready}` : ""}{cap.status === "saved" ? ", saved" : ", being checked with the farmer"}</span>}
          {n.rail && <span><b>Offer:</b> {n.rail.offer ? `${plainPrice(n.rail.offer, n.rail.currency || "IDR")}/kg` : "working it out"}{n.rail.counter ? `, farmer asks ${plainPrice(n.rail.counter, n.rail.currency || "IDR")}` : ""}</span>}
          {n.offer_saved && <span><b>Deal:</b> {n.offer_saved.status === "escalated" ? "sent to you to decide" : "agreed, waiting for your approval"}</span>}
        </footer>
      )}
    </article>
  );
}

// What is on the phone right now, in one line: calls on now and phones ringing, and what is waiting.
function LiveNow({ calls }) {
  const on = calls.filter((c) => c.status === "on_call").length;
  const ringing = calls.filter((c) => c.status === "queued" && c.channel === "twilio" && c.dialed_at).length;
  const demo = calls.filter((c) => c.status === "queued" && (c.channel || "browser") === "browser").length;
  const callBack = calls.filter((c) => c.status === "queued" && c.channel === "twilio" && !c.dialed_at && (c.attempt || 1) > 1).length;
  const n = (k, one, many) => `${k} ${k === 1 ? one : many}`;
  const waiting = [demo && `${n(demo, "demo call", "demo calls")} waiting on the demo phone`, callBack && `${n(callBack, "missed call", "missed calls")} to call back`].filter(Boolean).join(", ");
  return (
    <p className="live-now" aria-live="polite">
      {on || ringing ? <><span className="dot-live" aria-hidden="true" /><b>{[on && `${n(on, "call", "calls")} on now`, ringing && `${n(ringing, "phone", "phones")} ringing`].filter(Boolean).join(", ")}</b>
          {on > 0 && <span className="muted">: {calls.filter((c) => c.status === "on_call").map((c) => c.farmer_name).slice(0, 4).join(", ")}{on > 4 ? " and others" : ""}</span>}</>
        : <b>No call is on right now.</b>}
      {waiting && <span className="muted"> {waiting}.</span>}
    </p>
  );
}

export default function Calls() {
  const { state } = useLive();
  const { cid, campaign } = useCrop();
  const [shown, setShown] = useState(null);
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");
  const [phone, setPhone] = useState(false);
  const calls = state ? inCampaign(state, state.calls, cid) : [];
  const farmers = new Map((state?.farmers || []).map((f) => [f.id, f]));
  const harvestOf = new Map((state?.harvests || []).filter((h) => h.call_id).map((h) => [h.call_id, h]));
  const offerOf = new Map((state?.offers || []).filter((o) => o.call_id).map((o) => [o.call_id, o]));
  const rows = calls.map((c) => {
    const h = harvestOf.get(c.id) || null;
    const o = offerOf.get(c.id) || null;
    const answers = Object.values(c.answers || {});
    const missed = NOT_REACHED.includes(c.outcome) || c.status === "dropped";
    return { c, h, o, answers, missed, f: farmers.get(c.farmer_id) || {} };
  }).sort((a, b) => {  // calls on now first, then finished calls (newest on top), calls still waiting at the end
    const rank = (c) => (c.status === "on_call" ? 0 : c.status === "queued" ? 2 : 1);
    return rank(a.c) - rank(b.c) || (when(b.c) || "").localeCompare(when(a.c) || "");
  });
  const count = (fn) => rows.filter(fn).length;
  const is = {
    all: () => true,
    harvest: (r) => !!r.h,
    unsure: (r) => r.h?.confidence === "unsure",
    missed: (r) => r.missed,
    offer: (r) => !!r.o,
    waiting: (r) => ["queued", "on_call"].includes(r.c.status),
  };
  const needle = q.trim().toLowerCase();
  const list = rows.filter(is[filter]).filter((r) => !needle || `${r.c.farmer_name} ${r.f.village || ""}`.toLowerCase().includes(needle));
  const waitingDemo = calls.filter((c) => c.status === "queued" && (c.channel || "browser") === "browser").length;
  const finished = count((r) => !["queued", "on_call"].includes(r.c.status));
  const stats = [
    { key: "all", n: finished, label: "calls made" },
    { key: "harvest", n: count(is.harvest), label: "harvests given", sub: `${fmtKg(rows.filter(is.harvest).reduce((n, r) => n + (r.h.kg || 0), 0))} kg` },
    { key: "unsure", n: count(is.unsure), label: "unsure answers", warn: true },
    { key: "missed", n: count(is.missed), label: "not reached", warn: true },
    { key: "offer", n: count(is.offer), label: "offers made" },
  ];
  const head = (
    <div className="page-head">
      <div>
        <h1>Calls{campaign.label ? <span className="h1-ctx">{campaign.label}</span> : null}</h1>
        <p>What each farmer told the agent. Click a call for the full recap and transcript.</p>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <DownloadLink path="/api/answers.csv" filename="answers.csv">Answers CSV</DownloadLink>
        <button type="button" className="btn" onClick={() => setPhone(true)}><Icon name="phone" size={16} />Demo phone{waitingDemo ? ` (${waitingDemo})` : ""}</button>
      </div>
    </div>
  );
  return (
    <Shell title="Calls" head={head}>
      {waitingDemo > 0 && !phone && (
        <div className="banner" role="status">
          {waitingDemo} demo call{waitingDemo > 1 ? "s are" : " is"} waiting for the demo phone (no phone line is set up, so the browser plays the farmer).
          <button type="button" className="btn sm" style={{ marginLeft: 10 }} onClick={() => setPhone(true)}>Open the demo phone</button>
        </div>
      )}
      <LiveNow calls={calls} />
      <LiveCalls calls={calls.filter((c) => c.status === "on_call")} farmers={farmers} />
      <div className="call-stats" role="group" aria-label="Filter calls">
        {stats.map((s) => (
          <button key={s.key} type="button" className={`call-stat ${filter === s.key ? "on" : ""} ${s.warn && s.n ? "warn" : ""}`} aria-pressed={filter === s.key} onClick={() => setFilter(s.key)}>
            <span>{s.label}</span><b>{s.n}</b>{s.sub && s.n > 0 && <small>{s.sub}</small>}
          </button>
        ))}
      </div>
      <section className="card answers-card" aria-labelledby="answers-title">
        <div className="card-head">
          <h2 id="answers-title">Answers</h2>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <select className="filter-select" aria-label="Show" value={filter} onChange={(e) => setFilter(e.target.value)}>
              {FILTERS.map((f) => <option key={f.key} value={f.key}>{f.label} ({count(is[f.key])})</option>)}
            </select>
            <input type="search" placeholder="Search farmer or village" aria-label="Search calls" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 220 }} />
          </div>
        </div>
        {list.length ? (
          <div className="table-wrap">
            <table className="answers">
              <thead>
                <tr><th>Farmer</th><th>Call</th><th>Harvest they gave</th><th className="c-offer">Offer</th><th className="c-other">Other answers</th></tr>
              </thead>
              <tbody>
                {list.map(({ c, h, o, answers, f }) => {
                  const chip = callChip(c);
                  const live = c.status === "on_call";
                  const open = !["queued", "on_call"].includes(c.status) || live;
                  return (
                    <tr key={c.id} className={`${open ? "clickable" : ""} ${live ? "is-live" : ""}`} onClick={open ? () => (live ? showLive(c.id) : setShown(c)) : undefined}
                      tabIndex={open ? 0 : undefined} onKeyDown={open ? (e) => { if (e.key === "Enter") (live ? showLive(c.id) : setShown(c)); } : undefined}>
                      <td>
                        <div className="who-cell"><Avatar name={c.farmer_name} cls="sm" /><div><b>{c.farmer_name}</b><span>{f.village || ""}{f.language ? `, ${f.language}` : ""}</span></div></div>
                      </td>
                      <td>
                        <Pill cls={chip.cls}>{chip.text}</Pill>
                        <small className="cell-sub">{KIND_WORD[c.kind] || c.kind}, {fmtWhen(when(c)) || "waiting"}{c.channel === "twilio" ? ", phone" : c.channel === "browser" ? ", demo" : ""}</small>
                      </td>
                      <td>
                        {h ? (
                          <span className="ans-harvest">
                            <b>{fmtKg(h.kg)} kg</b> ready {day(h.ready_date)}
                            <small><span className={h.confidence === "unsure" ? "tag unsure" : "tag firm"}>{h.confidence === "unsure" ? "unsure" : "firm"}</span>{h.every_days ? `, every ${h.every_days} days` : ""}{h.edited_by ? `, edited by ${h.edited_by}` : ""}</small>
                          </span>
                        ) : c.harvest_read_back ? <span className="muted small">Read back, not saved ({fmtKg(c.harvest_read_back.kg)} kg): open to save</span>
                          : open ? <span className="muted small">{c.kind === "confirm" ? "Confirmation of the deal" : "No harvest given"}</span> : <span className="muted small">–</span>}
                      </td>
                      <td className="c-offer">
                        {o ? <span className="ans-offer"><b>{fmtKg(o.kg)} kg</b> at {plainPrice(o.price_per_kg, o.currency || "IDR")}<small>{({ pending: "waiting for you", escalated: "above the ceiling", approved: "approved", rejected: "rejected" })[o.status] || o.status}</small></span>
                          : <span className="muted small">–</span>}
                      </td>
                      <td className="c-other">
                        {answers.length ? (
                          <ul className="ans-list">
                            {answers.slice(0, 3).map((a) => <li key={a.question}><span>{a.question}</span><b>{a.answer === "skipped" ? "no answer" : String(a.answer)}</b></li>)}
                          </ul>
                        ) : c.summary ? <span className="small">{c.summary}</span> : <span className="muted small">–</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <p className="muted">{rows.length ? "No call matches." : "No calls yet for this campaign. Start calling on the Campaign page."}</p>}
      </section>

      {phone && (
        <aside className="phone-drawer" aria-label="Demo phone">
          <div className="phone-drawer-head">
            <b>Demo phone</b>
            <small>Plays the farmer's phone when no phone line is set up</small>
            <button type="button" className="btn sm" onClick={() => setPhone(false)} aria-label="Close the demo phone">Close</button>
          </div>
          {/* Same origin, so the call client shares the sign-in; the microphone is allowed for the frame. */}
          <iframe title="Demo phone" src="/call.html?embed" allow="microphone; autoplay" />
        </aside>
      )}
      <CallRecap call={shown} onClose={() => setShown(null)} />
    </Shell>
  );
}
