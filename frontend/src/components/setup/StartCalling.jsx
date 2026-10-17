import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { campaignFor, useCrop } from "../../campaigns.jsx";
import { api, can, startUrl, stopUrl } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton, Icon } from "../../ui.jsx";
import StepTop from "./StepTop.jsx";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 15 }, (_, i) => `${String(i + 5).padStart(2, "0")}:00`); // 05:00 to 19:00
const daysText = (days) => (days.length === 7 ? "Every day" : days.join() === "0,1,2,3,4" ? "Monday to Friday"
  : days.join() === "0,1,2,3,4,5" ? "Monday to Saturday" : days.map((d) => DAYS[d]).join(", "));

// When the agent starts this campaign's calls by itself: on/off, the weekdays and the hour (Jakarta time).
function AutoCalls({ campaign, phoneCalls, weeklyJob }) {
  const act = useAct();
  const saved = campaign.weekly || {};
  const [days, setDays] = useState(saved.days || [0]);
  const [time, setTime] = useState(saved.time || "06:00");
  useEffect(() => { setDays(saved.days || [0]); setTime(saved.time || "06:00"); }, [campaign.id, saved.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps
  const allowed = can("campaign.run");
  const save = (patch, message) => act(() => api(`/api/campaigns/${campaign.id}/schedule`, { method: "PUT",
    body: { enabled: !!saved.enabled, channel: phoneCalls ? "twilio" : "browser", days, time, ...patch } }), message);
  const toggleDay = (d) => {
    const next = days.includes(d) ? days.filter((x) => x !== d) : [...days, d].sort();
    if (!next.length) return;
    setDays(next);
    if (saved.enabled) save({ days: next }, `Automatic calls: ${daysText(next)} at ${time}.`);
  };
  const changed = saved.enabled && (days.join() !== (saved.days || [0]).join() || time !== (saved.time || "06:00"));
  return (
    <div className="auto-calls">
      <label className="auto-head">
        <input type="checkbox" checked={!!saved.enabled} disabled={!allowed}
          onChange={(e) => save({ enabled: e.target.checked }, e.target.checked ? `Automatic calls on: ${daysText(days)} at ${time}${phoneCalls ? ", on the farmers' phones" : ""}.` : "Automatic calls off.")} />
        <span><b>Call automatically</b><small>{saved.enabled ? `${daysText(saved.days || [0])} at ${saved.time || "06:00"} (Jakarta time)` : "Off: you start the calls yourself"}</small></span>
      </label>
      <div className="auto-days" role="group" aria-label="Days">
        {DAYS.map((d, i) => (
          <button key={d} type="button" className={days.includes(i) ? "on" : ""} aria-pressed={days.includes(i)} disabled={!allowed} onClick={() => toggleDay(i)}>{d}</button>
        ))}
      </div>
      <div className="auto-time">
        <label>At
          <select value={time} disabled={!allowed} onChange={(e) => { setTime(e.target.value); if (saved.enabled) save({ time: e.target.value }, `Automatic calls: ${daysText(days)} at ${e.target.value}.`); }}>
            {HOURS.map((h) => <option key={h}>{h}</option>)}
          </select>
        </label>
        {changed && <button type="button" className="btn sm on-ink" onClick={() => save({}, "Schedule saved.")}>Save</button>}
      </div>
      {saved.enabled && !weeklyJob && <small className="auto-warn">The scheduler is not set up on this server yet (JOB_TOKEN), so automatic calls will not start.</small>}
    </div>
  );
}

// Step 3: the agent phones this campaign's farmers (outbound). With real phone calls switched on the farmers' own
// phones ring; without them (the demo) the Calls page plays the farmer's phone.
export default function StartCalling({ state, toCall }) {
  const act = useAct();
  const navigate = useNavigate();
  const { cid } = useCrop();
  const campaign = campaignFor(state, cid);
  const running = campaign.status === "running";
  const s = state.settings || {};
  const minutes = Math.round((s.max_call_seconds || 360) / 60);
  const phoneCalls = !!s.phone_calls;
  const byPhone = campaign.channel === "twilio";
  const start = async (channel) => {
    const r = await act(() => api(startUrl(cid), { body: { kind: "collect", channel } }),
      channel === "twilio" ? (x) => `Calling ${x.queued} farmers' phones, one at a time.` : (x) => `${x.queued} demo calls ready on the Calls page.`);
    if (r) navigate(channel === "twilio" ? "/forecast" : "/calls");
  };
  const who = `${toCall} ${toCall === 1 ? "farmer" : "farmers"}`;
  // While calls run: this round's calls (since the campaign started calling), waiting, done and answered.
  const since = campaign.started_at || "";
  const round = running ? state.calls.filter((c) => c.campaign_id === cid && (c.created_at || "") >= since.slice(0, 19) && c.kind === campaign.kind) : [];
  const roundWaiting = round.filter((c) => ["queued", "on_call"].includes(c.status)).length;
  const roundDone = round.length - roundWaiting;
  const answeredIds = new Set(state.harvests.filter((h) => h.call_id).map((h) => h.call_id));
  const offerIds = new Set(state.offers.filter((o) => o.call_id).map((o) => o.call_id));
  const roundGot = round.filter((c) => answeredIds.has(c.id) || offerIds.has(c.id)).length;
  const gapLabel = campaign.gap_week ? `week ${campaign.gap_week}` : "the short week";
  return (
    <section className="card dark start-card" aria-labelledby="campaign-title">
      <StepTop n={3} label="Call" done={false} word={running ? "Calling now" : toCall ? "Ready to call" : "Nothing to call"} cls={running ? "leaf" : ""} />
      {running ? (
        <>
          <div className="step-head">
            <h2 id="campaign-title">{campaign.kind === "gap_fill" ? `Gap-fill calls running for ${gapLabel}` : "Harvest calls running"}</h2>
            <span className="sub">{campaign.kind === "gap_fill"
              ? "The agent is asking farmers who can harvest earlier to bring fruit into the short week, at a better price inside your range. Each deal waits for your approval."
              : "The agent is asking each farmer for their next harvest. Answers go straight into the forecast."}</span>
          </div>
          <div className="stats" id="campaign-lines">
            <div><b>{roundWaiting}</b><span>still to call</span></div>
            <div><b>{roundDone}</b><span>calls done</span></div>
            <div><b>{roundGot}</b><span>{campaign.kind === "gap_fill" ? "offers" : "answers"}</span></div>
          </div>
        </>
      ) : (
        <>
          <div className="step-head">
            <h2 id="campaign-title">Call the farmers</h2>
            <span className="sub">The AI agent phones the farmers who need a harvest call, asks about their next harvest and saves the answer. Nothing is agreed without your approval.</span>
          </div>
          <div className="stats" id="campaign-lines">
            <div><b>{toCall}</b><span>to call</span></div>
            <div><b>≤ {minutes} min</b><span>per call</span></div>
            <div><b>W1 to W{campaign.weeks || s.weeks || 5}</b><span>asked about</span></div>
          </div>
        </>
      )}
      <p className="call-mode">
        <Icon name="phone" size={14} />
        {phoneCalls ? <span><b>Real phone calls.</b> {s.phone_calls_note}</span>
          : <span><b>Demo mode.</b> No phone line is set up, so the Calls page plays the farmer's phone: the agent calls it and you answer as the farmer.</span>}
      </p>
      <div className="start-acts">
        {running ? <>
          {byPhone && <span className="pill lg dot running" style={{ alignSelf: "flex-start", background: "var(--ink-2)", color: "var(--on-ink)" }}>Calling phones, one at a time</span>}
          {byPhone ? <Link className="btn mint big block" to="/forecast">Watch the calls</Link> : <Link className="btn mint big block" to="/calls">Open the demo phone</Link>}
          <ActButton need="campaign.run" className="btn on-ink block" busy="Stopping…" run={() => act(() => api(stopUrl(cid), { body: {} }), "Calling stopped.")}>Stop calling</ActButton>
        </> : phoneCalls ? <>
          <ActButton need="campaign.run" className="btn mint big block" busy="Starting…" disabled={!toCall} run={() => start("twilio")}>
            <Icon name="phone" />{toCall ? `Call ${who} now` : "Add farmers to call"}
          </ActButton>
          <ActButton need="campaign.run" className="btn on-ink block" busy="Starting…" disabled={!toCall} run={() => start("browser")}>Try it on the demo phone</ActButton>
        </> : (
          <ActButton need="campaign.run" className="btn mint big block" busy="Starting…" disabled={!toCall} run={() => start("browser")}>
            <Icon name="phone" />{toCall ? `Call ${who} (demo)` : "Add farmers to call"}
          </ActButton>
        )}
      </div>
      <AutoCalls campaign={campaign} phoneCalls={phoneCalls} weeklyJob={!!s.weekly_job} />
    </section>
  );
}
